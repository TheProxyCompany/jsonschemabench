#!/bin/bash

. /opt/conda/etc/profile.d/conda.sh

if [ ! -d "/home/jsonschemabench" ]; then
  git clone https://github.com/epfl-dlab/jsonschemabench.git /home/jsonschemabench
else
  cd /home/jsonschemabench && git pull
fi

conda activate default
