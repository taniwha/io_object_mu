import bpy
import sys
from io_object_mu.import_mu import import_mu

collection = bpy.context.layer_collection.collection
base = sys.argv.index("--")
argv = sys.argv[base:]
print(sys.argv)
import_mu(collection, argv[1], True, False, False)