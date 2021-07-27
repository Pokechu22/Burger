from typing import Iterator, List
from lawu import ast


def transform_floats(o):
  if isinstance(o, float):
    return round(o, 5)
  elif isinstance(o, dict):
    return {k: transform_floats(v) for k, v in o.items()}
  elif isinstance(o, (list, tuple)):
    return [transform_floats(v) for v in o]
  return o


def yield_inst(code, find_ins: List[str] = None) -> Iterator[ast.Instruction]:
  for ins in code:
    if isinstance(ins, ast.Instruction):
      if find_ins is None or ins.name in find_ins:
        yield ins

    if isinstance(ins, ast.TryCatch) or isinstance(ins, ast.Finally):
      yield from yield_inst(ins, find_ins)
