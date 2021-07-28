import json

from lawu.ast import String, Number
from .topping import Topping


class VersionTopping(Topping):
  """Provides the protocol version."""

  PROVIDES = [
      'version.protocol',
      'version.id',
      'version.name',
      'version.data',
      'version.is_flattened',
      'version.entity_format',
  ]

  DEPENDS = ['identify.nethandler.server', 'identify.anvilchunkloader']

  @staticmethod
  def act(aggregate, classloader, verbose=False):
    aggregate.setdefault('version', {})

    try:
      # 18w47b+ has a file that just directly includes this info
      with classloader.open('version.json') as fin:
        version_json = json.load(fin)
        aggregate['version']['data'] = version_json['world_version']
        aggregate['version']['protocol'] = version_json['protocol_version']
        aggregate['version']['name'] = version_json['name']
        # Starting with 1.14.3-pre1, the 'id' field began being used
        # for the id used on the downloads site.  Prior to that, (1.14.2)
        # 'name' was used, and 'id' looked like
        # '1.14.2 / f647ba8dc371474797bee24b2b312ff4'.
        # Our heuristic for this is whether the ID is shorter than the name.
        if len(version_json['id']) <= len(version_json['name']):
          if verbose:
            print(f"Using id {version_json['id']} over name "
                  f"{version_json['name']} for id as it is shorter")
          aggregate['version']['id'] = version_json['id']
        else:
          if verbose:
            print(f"Using name {version_json['name']} over id "
                  f"{version_json['id']} for id as it is shorter")
          aggregate['version']['id'] = version_json['name']
    except:
      # Find it manually
      VersionTopping.get_protocol_version(aggregate, classloader, verbose)
      VersionTopping.get_data_version(aggregate, classloader, verbose)

    if 'data' in aggregate['version']:
      data_version = aggregate['version']['data']
      # Versions after 17w46a (1449) are flattened
      aggregate['version']['is_flattened'] = (data_version > 1449)
      if data_version >= 1461:
        # 1.13 (18w02a and above, 1461) uses yet another entity format
        aggregate['version']['entity_format'] = '1.13'
      elif data_version >= 800:
        # 1.11 versions (16w32a and above, 800) use one entity format
        aggregate['version']['entity_format'] = '1.11'
      else:
        # Old entity format
        aggregate['version']['entity_format'] = '1.10'
    else:
      aggregate['version']['is_flattened'] = False
      aggregate['version']['entity_format'] = '1.10'

  @staticmethod
  def get_protocol_version(aggregate, classloader, verbose):
    versions = aggregate['version']
    if 'nethandler.server' in aggregate['classes']:
      nethandler = aggregate['classes']['nethandler.server']
      cf = classloader[nethandler]
      version = None
      looking_for_version_name = False

      for method in cf.methods:
        for ins in method.code.find_ins('bipush', 'sipush'):
          version = ins.operands[0].value

      if version is None:
        if verbose:
          print('Unable to find initial version value')
        return

      for method in cf.methods:
        for ins in method.code.find_ins('ldc'):
          opr = ins.operands[0]
          if isinstance(opr, String):
            if 'multiplayer.disconnect.outdated_client' in opr.value:
              versions['protocol'] = version
              looking_for_version_name = True
              continue
            elif looking_for_version_name:
              versions['name'] = opr.value
              versions['id'] = versions['name']
              return
            elif 'Outdated server!' in opr.value:
              versions['protocol'] = version
              cut = len("Outdated server! I'm still on ")
              versions['name'] = opr.value[cut:]
              versions['id'] = versions['name']
              return

    if verbose:
      print('Unable to determine protocol version')

  @staticmethod
  def get_data_version(aggregate, classloader, verbose):
    if 'anvilchunkloader' in aggregate['classes']:
      anvilchunkloader = aggregate['classes']['anvilchunkloader']
      cf = classloader[anvilchunkloader]

      for method in cf.methods:

        # In 18w21a+, there are two places that reference DataVersion,
        # one which is querying it and one which is saving it.
        # We don't want the one that's querying it;
        # if 'hasLegacyStructureData' is present then we're in the
        # querying one so break and try the next method
        def f(ins):
          if ins.name not in ('ldc', 'ldc_w'):
            return False
          o = ins.operands[0]
          return isinstance(o, String) and o.value == 'hasLegacyStructureData'

        if next(method.code.find(name='instruction', f=f), False):
          continue

        found_version = None

        ins_gen = method.code.find_ins('ldc', 'ldc_w', 'bipush', 'sipush')
        for ins in ins_gen:
          opr = ins.operands[0]
          if isinstance(opr, String) and opr.value == 'DataVersion':
            opr = next(ins_gen).operands[0]
            if isinstance(opr, Number):
              found_version = opr.value
            break

        if found_version is not None:
          aggregate['version']['data'] = found_version
          return

    if verbose:
      print('Unable to determine data version')
