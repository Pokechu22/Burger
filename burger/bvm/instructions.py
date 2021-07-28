from lawu import ast
from collections import defaultdict

InstructionMap = {}


class VMState:
  __slots__ = ('index', 'locals', 'stack')

  def __init__(self) -> None:
    self.index = 0
    self.locals = defaultdict(object)
    self.stack = []

  stack_push = stack.append
  stack_pop = stack.pop


def instr(*args):
  def inner(f):
    for arg in args:
      InstructionMap[arg] = f

  return inner


@instr('bipush', 'sipush')
def push(ins: ast.Instruction, state: VMState) -> None:
  state.stack_push(ins.operands[0].value)


@instr('fconst_0', 'fconst_1', 'fconst_2', 'dconst_0', 'dconst_1', 'dconst_2')
def float_const(ins: ast.Instruction, state: VMState) -> None:
  state.stack_push(float(ins.name[-1]))


@instr('aconst_null')
def null_const(ins: ast.Instruction, state: VMState) -> None:
  state.stack_push(None)


@instr('ldc', 'ldc_w', 'ldc2_w')
def load_const(ins: ast.Instruction, state: VMState) -> None:
  opr = ins.operands[0]

  if isinstance(opr, ast.ClassReference):
    state.stack_push(f'{opr.descriptor}.class')
  elif isinstance(opr, ast.String) or isinstance(opr, ast.Number):
    state.stack_push(opr.value)
  else:
    raise RuntimeError('Unhandled operand for load_const')


@instr('astore', 'istore', 'lstore', 'fstore', 'dstore')
def store_local(ins: ast.Instruction, state: VMState) -> None:
  state.locals[ins.operands[0].value] = state.stack_pop()


@instr('aload', 'iload', 'lload', 'fload', 'dload')
def load_local(ins: ast.Instruction, state: VMState) -> None:
  state.stack_push(state.locals[ins.operands[0].value])


@instr('dup')
def dup_stack(ins: ast.Instruction, state: VMState) -> None:
  state.stack_push(state.stack[-1])
