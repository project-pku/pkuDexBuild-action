# A script that compiles collections of subdexes as specified by the config.json
import json
import commentjson
import sys
import os, os.path
from pathlib import Path
import copy
from jsonpath_ng import parse

# Merges two dictionaries in-place.
# Note: If the a key corresponds to an array in both dicts, the elements of
#   the new array are appended to the old one rather than replacing them.
def merge_dicts(base, new):
  for k, v in new.items():
    if type(v) is list and k in base and type(base[k]) is list:
      base[k].extend(x for x in v if x not in base[k])
    elif type(v) is dict and k in base and type(base[k]) is dict:
      merge_dicts(base[k], v)
    else:
      base[k] = v

# Used to define override-like commands
# max_iter (default 10) is the maximum number of iterations to unroll.
# if the limit is hit, the dex is likely to have a circular override dependency.
def apply_override_like_cmd(cmd_name, dex, cmd_expr, getVal, max_iter = 10):
  for i in range(max_iter+2): # one because range end is exclusive
                              # one to check if max_iter was too low
    # find paths of all override commands
    overrideList = cmd_expr.find(dex)
    if not overrideList:
      break # break early if no more overrides
    
    # halt if max_iter isn't enough iterations to unroll
    if i == max_iter+1:
      raise Exception(f"Couldn't finish index_override commands. Seems {max_iter} iterations was not enough to unroll the dex. Is this not a DAG?")

    # apply override to each path
    for match in overrideList:
      try:
        baseValue = getVal(dex, match)
      except:
        # halt if override base value not found
        raise Exception(f"{cmd_name} cmd referenced a non-existant path. See: {match.full_path}.")

      match.context.full_path.update(dex, baseValue)

# Applies the "$override" commands in a given dex, then removes them.
OVERRIDE_EXPRESSION = parse("$..'$override'")
def get_val_override(dex, match) :
  basePath = match.value
  baseValue = copy.deepcopy(parse(basePath).find(dex)[0].value)
  newValue = match.context.value
  newValue.pop("$override")
  if isinstance(baseValue, dict): # base is a dict
    merge_dicts(baseValue, newValue) # merge overriden dict with base
  else: # base is a value
    # make sure that child has 0 proprties (the override command was removed)
    assert len(newValue) == 0, f"Trying to override a dict {match.context.full_path} w/ a value {basePath}"
  return baseValue
def apply_overrides(dex):
  apply_override_like_cmd("Override", dex, OVERRIDE_EXPRESSION, get_val_override)

# Applies the "$index_override" commands in a given dex, removing them in the process
INDEX_OVERRIDE_EXPRESSION = parse("$..'$index_override'")
def get_val_index_override(dex, match) :
  return copy.deepcopy(match.context.context.value[match.value])
def apply_index_overrides(dex):
  apply_override_like_cmd("Index Override", dex, INDEX_OVERRIDE_EXPRESSION, get_val_index_override)

# Removes all properties in a dict, even those nested in lists, that satisfy func
# func is a function that takes 1 string argument.
def remove_key(d, func):
  if isinstance(d, dict):
    for key in list(d.keys()):
      if func(key):
        d.pop(key)
      else:
        remove_key(d[key], func)
  elif isinstance(d, list):
    for obj in d:
      remove_key(obj, func)

# Returns true if the given string starts with "$temp_"
def isTemp(key):
  return key.startswith("$temp_")

# ----------------
## Begin Script
# ----------------
# initialize
root = os.getcwd() #current working directory
build_path = os.path.join(root, "build")
config = commentjson.load(open(os.path.join(root, sys.argv[1]), encoding="utf8"))

# collect subdexes
dexes = {}
for _, manifestLoc in config["Sub-Configs"].items():
  manifestRoot = os.path.dirname(manifestLoc)
  manifest = commentjson.load(open(os.path.join(root, manifestLoc), encoding="utf8"))
  for dexType, dexLocOrLocs in manifest.items():
    # cast single dex location to array of locations
    dexLocs = [dexLocOrLocs] if type(dexLocOrLocs) == str else dexLocOrLocs
    for dexLoc in dexLocs:
      fullDexLoc = os.path.join(manifestRoot, dexLoc)
      if dexType in dexes:
        dexes[dexType].append(fullDexLoc)
      else:
        dexes[dexType] = [fullDexLoc]

# ensure build path exists
Path(build_path).mkdir(parents=True, exist_ok=True)

# process each dex type (in reverse order so that first dexes overwrite later ones)
for dexType, dexList in dexes.items():
  # merge datadexes
  first = True
  base = None
  for dexLoc in reversed(dexList):
    sdex = commentjson.load(open(os.path.join(root, dexLoc), encoding="utf8"))
    if first:
      base = sdex
      first = False
    else:
      merge_dicts(base, sdex)

  # unroll the final datadex
  apply_overrides(base) #first apply override commands
  apply_index_overrides(base) #second apply index_override commands
  remove_key(base, isTemp) # finally, remove all temp properties

  # post-processing, write file
  with open(os.path.join(build_path,'{0}Dex.json'.format(dexType)), 'w', encoding='utf-8') as f:
    f.write(json.dumps(base,separators=(',', ':')))
  print("Compiled {0}Dex...".format(dexType))


# build new config
newconfig = {
  "Name": config["Name"],
  "Version": config["Version"],
  "Dexes": {}
}

# add list of dexes to config
for dexType in dexes:
  newconfig["Dexes"][dexType] = f"{dexType}Dex.json"

# add new config to build
with open(os.path.join(build_path,'config.json'), 'w', encoding='utf-8') as f:
  f.write(json.dumps(newconfig,separators=(',', ':')))

print("\nFinished compiling dexes!")