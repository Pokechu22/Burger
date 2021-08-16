def transform_floats(o):
  if isinstance(o, float):
    return round(o, 5)
  elif isinstance(o, dict):
    return {k: transform_floats(v) for k, v in o.items()}
  elif isinstance(o, (list, tuple)):
    return [transform_floats(v) for v in o]
  return o
