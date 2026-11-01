# Installed addins for the offline addin test (after a device script): alpha, an older version with the uninstall.sh
# the installer leaves; gamma, made by hand (no uninstall.sh), at the catalog's version.
set -e
A=/data/mpc-addins; mkdir -p $A/alpha-addin $A/gamma-addin
printf 'ADDIN_ID=alpha-addin\nADDIN_NAME="Alpha addin"\nADDIN_SO=alpha_addin.so\nADDIN_VERSION="0.0.1"\n' > $A/alpha-addin/addin.manifest
touch $A/alpha-addin/alpha_addin.so; printf '#!/bin/sh\nexit 0\n' > $A/alpha-addin/uninstall.sh
printf 'ADDIN_ID=gamma-addin\nADDIN_NAME="Gamma addin"\nADDIN_SO=gamma_addin.so\nADDIN_VERSION=0.3.0\n' > $A/gamma-addin/addin.manifest
touch $A/gamma-addin/gamma_addin.so
