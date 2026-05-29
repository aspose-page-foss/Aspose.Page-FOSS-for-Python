import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.context import ExecutionContext, GraphicsState
from aspose.page.ps.dsc import parse_dsc_comments
from aspose.page.ps.errors import PsRangeError, PsUndefinedError
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.ps.objects import (
    PsArray,
    PsDict,
    PsFontId,
    PsFile,
    PsGState,
    PsMark,
    PsName,
    PsProcedure,
    PsSave,
    PsString,
)
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.parser import PsParser
from aspose.page.ps.stack import PsStack
from aspose.page.ps.tokenizer import PsTokenizer
from aspose.page.ps.vm import save_state, restore_state


def make_context() -> ExecutionContext:
    systemdict = PsDict({})
    userdict = PsDict({})
    dict_stack = PsStack([systemdict, userdict])
    return ExecutionContext(
        operand_stack=PsStack(),
        execution_stack=PsStack(),
        dictionary_stack=dict_stack,
        graphics_state_stack=PsStack([GraphicsState()]),
        userdict=userdict,
        systemdict=systemdict,
    )


class TestTokenizerAndParser(unittest.TestCase):
    def test_tokenizer_basic(self):
        data = b"/name 123 4.5 (hi) [1 2] { /x 1 } %comment\n"
        tokenizer = PsTokenizer(data)
        kinds = []
        values = []
        while True:
            tok = tokenizer.next_token()
            if tok is None:
                break
            kinds.append(tok.kind)
            values.append(tok.value)
        self.assertIn("comment", kinds)
        self.assertIn("array_start", kinds)
        self.assertIn("procedure_start", kinds)
        self.assertIn("name", kinds)
        self.assertIn("number", kinds)

    def test_parser_structures(self):
        data = b"[1 2] << /A 1 /B 2 >> { /x 1 }"
        parser = PsParser(PsTokenizer(data))
        objs = parser.parse_all()
        self.assertIsInstance(objs[0], PsArray)
        self.assertIsInstance(objs[1], PsDict)
        self.assertIsInstance(objs[2], PsProcedure)
        self.assertEqual(objs[1].items.get("A"), 1)


class TestStackAndVM(unittest.TestCase):
    def test_stack_underflow(self):
        stack = PsStack()
        with self.assertRaises(PsRangeError):
            stack.pop()

    def test_save_restore(self):
        ctx = make_context()
        ctx.operand_stack.push(1)
        state = save_state(ctx)
        save_obj = PsSave(state)
        ctx.operand_stack.push(2)
        restore_state(ctx, save_obj.state)
        self.assertEqual(len(ctx.operand_stack), 1)
        self.assertEqual(ctx.operand_stack.peek(), 1)


class TestInterpreterSemantics(unittest.TestCase):
    def test_mark_semantics(self):
        registry = OperatorRegistry()

        def op_mark(ctx):
            ctx.operand_stack.push(PsMark())

        def op_counttomark(ctx):
            count = 0
            for item in reversed(ctx.operand_stack._items):
                if isinstance(item, PsMark):
                    ctx.operand_stack.push(count)
                    return
                count += 1
            raise PsRangeError("no mark found")

        def op_cleartomark(ctx):
            while len(ctx.operand_stack) > 0:
                item = ctx.operand_stack.pop()
                if isinstance(item, PsMark):
                    return
            raise PsRangeError("no mark found")

        registry.register("mark", op_mark)
        registry.register("counttomark", op_counttomark)
        registry.register("cleartomark", op_cleartomark)

        interpreter = PsInterpreter(registry)
        ctx = make_context()
        interpreter.execute_objects(
            [PsName("mark"), 1, 2, PsName("counttomark")], ctx
        )
        self.assertEqual(ctx.operand_stack._items[-1], 2)

        ctx = make_context()
        interpreter.execute_objects(
            [PsName("mark"), 1, 2, PsName("cleartomark")], ctx
        )
        self.assertEqual(len(ctx.operand_stack), 0)

    def test_gstate_object(self):
        registry = OperatorRegistry()

        def op_gstate(ctx):
            ctx.operand_stack.push(PsGState(ctx.graphics_state_stack.peek()))

        def op_setgstate(ctx):
            gs = ctx.operand_stack.pop()
            ctx.graphics_state_stack.pop()
            ctx.graphics_state_stack.push(gs.state)

        registry.register("gstate", op_gstate)
        registry.register("setgstate", op_setgstate, min_operands=1)
        interpreter = PsInterpreter(registry)
        ctx = make_context()
        ctx.graphics_state_stack.push(GraphicsState(line_width=5))
        interpreter.execute_objects([PsName("gstate")], ctx)
        gstate_obj = ctx.operand_stack.pop()
        self.assertEqual(gstate_obj.state.line_width, 5)

    def test_file_and_fontid(self):
        registry = OperatorRegistry()

        def op_file(ctx):
            mode = ctx.operand_stack.pop()
            name = ctx.operand_stack.pop()
            if isinstance(name, PsString):
                name_val = name.value.decode("latin-1", errors="ignore")
            else:
                name_val = str(name)
            if isinstance(mode, PsString):
                mode_val = mode.value.decode("latin-1", errors="ignore")
            else:
                mode_val = str(mode)
            ctx.operand_stack.push(PsFile(name=name_val, mode=mode_val))

        def op_fontid(ctx):
            ctx.operand_stack.push(PsFontId(1))

        registry.register("file", op_file, min_operands=2)
        registry.register("fontid", op_fontid)
        interpreter = PsInterpreter(registry)
        ctx = make_context()
        ctx.operand_stack.push(PsString(b"sample.ps"))
        ctx.operand_stack.push(PsString(b"r"))
        interpreter.execute_objects([PsName("file")], ctx)
        file_obj = ctx.operand_stack.pop()
        self.assertEqual(file_obj.name, "sample.ps")
        interpreter.execute_objects([PsName("fontid")], ctx)
        font_id = ctx.operand_stack.pop()
        self.assertEqual(font_id.id, 1)

    def test_operator_dispatch_errors(self):
        registry = OperatorRegistry()
        interpreter = PsInterpreter(registry)
        ctx = make_context()
        with self.assertRaises(PsUndefinedError):
            interpreter.execute_objects([PsName("unknown")], ctx)

        def op_one(ctx):
            ctx.operand_stack.pop()

        registry.register("one", op_one, min_operands=1)
        with self.assertRaises(PsRangeError):
            interpreter.execute_objects([PsName("one")], ctx)

    def test_execute_sample_with_dict_and_procedure(self):
        registry = OperatorRegistry()
        interpreter = PsInterpreter(registry)
        ctx = make_context()

        def op_add(ctx):
            b = ctx.operand_stack.pop()
            a = ctx.operand_stack.pop()
            ctx.operand_stack.push(a + b)

        def op_def(ctx):
            value = ctx.operand_stack.pop()
            key = ctx.operand_stack.pop()
            if isinstance(key, PsName):
                ctx.dictionary_stack.peek().items[key.value] = value
            else:
                ctx.dictionary_stack.peek().items[str(key)] = value

        registry.register("add", op_add, min_operands=2)
        registry.register("def", op_def, min_operands=2)

        sample = b"/x 5 def /p { 1 2 add } def x p"
        interpreter.execute(sample, ctx)
        self.assertEqual(ctx.operand_stack.pop(), 3)
        self.assertEqual(ctx.operand_stack.pop(), 5)


class TestDscParsing(unittest.TestCase):
    def test_dsc_metadata(self):
        data = (
            b"%%BoundingBox: 0 0 100 200\n"
            b"%%HiResBoundingBox: 0.1 0.2 100.3 200.4\n"
            b"%%DocumentMedia: Letter 612 792 0 () ()\n"
            b"%%Title: Sample\n"
            b"%%CreationDate: Today\n"
            b"%%LanguageLevel: 3\n"
        )
        meta = parse_dsc_comments(data)
        self.assertEqual(meta.bounding_box, (0, 0, 100, 200))
        self.assertEqual(meta.hires_bounding_box, (0.1, 0.2, 100.3, 200.4))
        self.assertEqual(meta.document_media_size, (612.0, 792.0))
        self.assertEqual(meta.title, "Sample")
        self.assertEqual(meta.language_level, 3)


if __name__ == "__main__":
    unittest.main()
