import importlib
import os

from neurst.layers.decoders.decoder import Decoder
from neurst.utils.registry import setup_registry

build_decoder, register_decoder = setup_registry(Decoder.REGISTRY_NAME, base_class=Decoder)

models_dir = os.path.dirname(__file__)
for file in os.listdir(models_dir):
    path = os.path.join(models_dir, file)
    if not file.startswith('_') and not file.startswith('.') and file.endswith('.py'):
        model_name = file[:file.find('.py')] if file.endswith('.py') else file
        module = importlib.import_module('neurst.layers.decoders.' + model_name)
