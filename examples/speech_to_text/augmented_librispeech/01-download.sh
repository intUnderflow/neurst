# Copyright 2020 ByteDance Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#!/usr/bin/env bash

set -e

if [[ ! -n "$1" ]] ;then
    echo "Usage: ./01-download.sh SAVE_PATH"
    exit 1
else
    DATA_PATH="$1"
fi

DATA_PATH=$DATA_PATH/raw/

mkdir -p $DATA_PATH

# Download from
#   https://github.com/alicank/Translation-Augmented-LibriSpeech-Corpus
# and acquire following zip files:
#   - train_100h.zip
#   - dev.zip
#   - test.zip

echo "Downloading Augmented LibriSpeech dataset..."
