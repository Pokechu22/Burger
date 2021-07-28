from lawu.cf import ClassFile
from lawu.constants import MethodHandle
from lawu.instructions import Instruction


class InvokeDynamicInfo:
  __slots__ = ('_ins', '_cf')

  def __init__(self, ins: Instruction, cf : ClassFile) -> None:
    self._ins = ins
    self._cf = cf

    const = ins.operands[0]
