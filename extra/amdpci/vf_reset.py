#!/usr/bin/env python3
import os
from tinygrad.runtime.support.system import System
from tinygrad.runtime.support.hcq import FileIOInterface

if __name__ == "__main__":
  # 0x74b5 is Instinct MI300X VF
  gpus = System.pci_scan_bus(0x1002, [(0xffff, [0x74b5])])
  if not gpus:
    print("No VF GPUs (0x74b5) found.")
    exit(0)

  for gpu in gpus:
    print(f"Resetting VF GPU at {gpu}...")
    dev_path = f"/sys/bus/pci/devices/{gpu}"
    
    # 1. Unbind from current driver if bound
    drv_path = f"{dev_path}/driver"
    if FileIOInterface.exists(drv_path):
      driver_name = os.path.basename(os.readlink(drv_path))
      print(f"Unbinding from {driver_name}...")
      try:
        with open(f"{drv_path}/unbind", "w") as f:
          f.write(gpu)
      except Exception as e:
        print(f"Failed to unbind {gpu}: {e}")

    # 2. Trigger Function Level Reset (FLR)
    reset_path = f"{dev_path}/reset"
    if FileIOInterface.exists(reset_path):
      print("Triggering Function Level Reset (FLR)...")
      try:
        with open(reset_path, "w") as f:
          f.write("1")
      except Exception as e:
        print(f"Failed to write to reset node: {e}. Try running as root/sudo.")
    else:
      print("FLR reset node does not exist for this device.")

    # 3. Bind to vfio-pci
    vfio_bind_path = "/sys/bus/pci/drivers/vfio-pci/bind"
    if FileIOInterface.exists(vfio_bind_path):
      override_path = f"{dev_path}/driver_override"
      try:
        with open(override_path, "w") as f:
          f.write("vfio-pci")
        with open(vfio_bind_path, "w") as f:
          f.write(gpu)
        print("Successfully bound to vfio-pci.")
      except Exception as e:
        print(f"Failed to bind to vfio-pci: {e}")
