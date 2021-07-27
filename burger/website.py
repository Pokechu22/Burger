import os
import urllib.request

import json

VERSION_MANIFEST = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
LEGACY_VERSION_META = "https://s3.amazonaws.com/Minecraft.Download/versions/%(version)s/%(version)s.json"  # DEPRECATED

_cached_version_manifest = None
_cached_version_metas = {}


def _load_json(url):
  stream = urllib.request.urlopen(url)
  try:
    return json.load(stream)
  finally:
    stream.close()


def get_version_manifest():
  global _cached_version_manifest
  if _cached_version_manifest:
    return _cached_version_manifest

  _cached_version_manifest = _load_json(VERSION_MANIFEST)
  return _cached_version_manifest


def get_version_meta(version, verbose):
  """
    Gets a version JSON file, first attempting the to use the version manifest
    and then falling back to the legacy site if that fails.
    Note that the main manifest should include all versions as of august 2018.
    """
  if version == "20w14~":
    # April fools snapshot, labeled 20w14~ ingame but 20w14infinite in the launcher
    version = "20w14infinite"

  if version in _cached_version_metas:
    return _cached_version_metas[version]

  version_manifest = get_version_manifest()
  for version_info in version_manifest["versions"]:
    if version_info["id"] == version:
      address = version_info["url"]
      break
  else:
    if verbose:
      print(
          "Failed to find %s in the main version manifest; using legacy site" %
          version)
    address = LEGACY_VERSION_META % {'version': version}
  if verbose:
    print("Loading version manifest for %s from %s" % (version, address))
  meta = _load_json(address)

  _cached_version_metas[version] = meta
  return meta


def get_asset_index(version_meta, verbose):
  """Downloads the Minecraft asset index"""
  if "assetIndex" not in version_meta:
    raise Exception("No asset index defined in the version meta")
  asset_index = version_meta["assetIndex"]
  if verbose:
    print("Assets: id %(id)s, url %(url)s" % asset_index)
  return _load_json(asset_index["url"])


def client_jar(version, verbose):
  """Downloads a specific version, by name"""
  filename = version + ".jar"
  if not os.path.exists(filename):
    meta = get_version_meta(version, verbose)
    if verbose:
      print("For version %s, the downloads section of the meta is %s" %
            (filename, meta["downloads"]))
    url = meta["downloads"]["client"]["url"]
    if verbose:
      print("Downloading %s from %s" % (version, url))
    urllib.request.urlretrieve(url, filename=filename)
  return filename


def latest_client_jar(verbose):
  manifest = get_version_manifest()
  return client_jar(manifest["latest"]["snapshot"], verbose)
