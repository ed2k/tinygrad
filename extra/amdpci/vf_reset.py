#!/usr/bin/env python3
import os
import time
from tinygrad.runtime.support.system import System
from tinygrad.runtime.support.hcq import FileIOInterface

if __name__ == "__main__":
  # 0x74b5 is Instinct MI300X VF
  gpus = System.pci_scan_bus(0x1002, [(0xffff, [0x74b5])])
  if not gpus:
    print("No VF GPUs (0x74b5) found.")
    exit(0)

  for gpu in gpus:
    print(f"========================================\nResetting VF GPU at {gpu}\n========================================")
    dev_path = f"/sys/bus/pci/devices/{gpu}"
    
    # 1. Unbind from current driver if bound
    drv_path = f"{dev_path}/driver"
    if FileIOInterface.exists(drv_path):
      driver_name = os.path.basename(os.readlink(drv_path))
      print(f"Current driver: {driver_name}. Unbinding...")
      try:
        with open(f"{drv_path}/unbind", "w") as f:
          f.write(gpu)
        time.sleep(0.5)
      except Exception as e:
        print(f"Failed to unbind {gpu}: {e}")

    # 2. Trigger Function Level Reset (FLR)
    reset_path = f"{dev_path}/reset"
    flr_success = False
    if FileIOInterface.exists(reset_path):
      print("Triggering Function Level Reset (FLR)...")
      try:
        with open(reset_path, "w") as f:
          f.write("1")
        time.sleep(1.0)
        flr_success = True
        print("FLR trigger sent successfully.")
      except Exception as e:
        print(f"FLR write failed: {e}")

    # 3. Fallback: PCI Remove and Rescan if FLR failed or device is still unresponsive
    config_responsive = False
    config_path = f"{dev_path}/config"
    if FileIOInterface.exists(config_path):
      try:
        with open(config_path, "rb") as f:
          header = f.read(4)
          # If it returns 0xffffffff or empty, config space is blocked
          if header and header != b'\xff\xff\xff\xff':
            config_responsive = True
      except Exception:
        pass

    if not flr_success or not config_responsive:
      print("Device is unresponsive or FLR failed. Triggering PCI bus remove & rescan...")
      
      # Remove device from PCI bus
      remove_path = f"{dev_path}/remove"
      if FileIOInterface.exists(remove_path):
        try:
          with open(remove_path, "w") as f:
            f.write("1")
          print(f"Removed {gpu} from PCI bus topology.")
          time.sleep(1.0)
        except Exception as e:
          print(f"Failed to remove device: {e}")

      # Rescan PCI bus
      rescan_path = "/sys/bus/pci/rescan"
      if FileIOInterface.exists(rescan_path):
        try:
          with open(rescan_path, "w") as f:
            f.write("1")
          print("PCI bus rescan completed.")
          time.sleep(2.0)
        except Exception as e:
          print(f"Failed to trigger PCI bus rescan: {e}")

    # 4. Check if the device is visible after rescan/reset
    if not FileIOInterface.exists(dev_path):
      print(f"Error: Device {gpu} did not reappear after reset/rescan!")
      continue

    # 5. Bind to vfio-pci
    vfio_bind_path = "/sys/bus/pci/drivers/vfio-pci/bind"
    if FileIOInterface.exists(vfio_bind_path):
      override_path = f"{dev_path}/driver_override"
      try:
        # Clear any old driver overrides and write clean vfio-pci override
        with open(override_path, "w") as f:
          f.write("vfio-pci")
        
        # If already bound to vfio-pci, skip bind to avoid errors
        current_drv_link = f"{dev_path}/driver"
        is_already_bound = False
        if FileIOInterface.exists(current_drv_link):
          if os.path.basename(os.readlink(current_drv_link)) == "vfio-pci":
            is_already_bound = True

        if not is_already_bound:
          with open(vfio_bind_path, "w") as f:
            f.write(gpu)
          time.sleep(0.5)
        
        # Verify binding
        if FileIOInterface.exists(current_drv_link) and os.path.basename(os.readlink(current_drv_link)) == "vfio-pci":
          print(f"Successfully bound {gpu} to vfio-pci.")
        else:
          print(f"Warning: Binding sent, but {gpu} is not bound to vfio-pci.")
      except Exception as e:
        print(f"Failed to bind to vfio-pci: {e}")
    else:
      print("Error: vfio-pci driver bind path not found. Is vfio-pci module loaded?")
