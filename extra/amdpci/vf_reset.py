#!/usr/bin/env python3
import os
import time
import subprocess
from tinygrad.runtime.support.system import System
from tinygrad.runtime.support.hcq import FileIOInterface

def run_cmd(cmd):
  print(f"[CMD] {cmd}")
  try:
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.stdout: print(f"STDOUT:\n{res.stdout.strip()}")
    if res.stderr: print(f"STDERR:\n{res.stderr.strip()}")
    return res.returncode
  except Exception as e:
    print(f"Failed to run cmd: {e}")
    return -1

if __name__ == "__main__":
  # Check no-iommu parameter
  noiommu_param = "/sys/module/vfio/parameters/enable_unsafe_noiommu_mode"
  if os.path.exists(noiommu_param):
    with open(noiommu_param, "r") as f:
      print(f"VFIO unsafe no-iommu mode parameter: {f.read().strip()}")
  else:
    print("VFIO unsafe no-iommu mode parameter does not exist.")

  # 0x74b5 is Instinct MI300X VF
  gpus = System.pci_scan_bus(0x1002, [(0xffff, [0x74b5])])
  if not gpus:
    print("No VF GPUs (0x74b5) found.")
    exit(0)

  for gpu in gpus:
    print(f"\n========================================\nResetting VF GPU at {gpu}\n========================================")
    dev_path = f"/sys/bus/pci/devices/{gpu}"
    
    # Print IOMMU Group Devices
    iommu_path = f"{dev_path}/iommu_group/devices"
    if os.path.exists(iommu_path):
      print(f"IOMMU Group Devices for {gpu}: {os.listdir(iommu_path)}")
    else:
      print(f"No IOMMU Group found for {gpu} (Device might be using no-iommu).")

    # 1. Unbind from current driver if bound
    drv_path = f"{dev_path}/driver"
    if FileIOInterface.exists(drv_path):
      driver_name = os.path.basename(os.readlink(drv_path))
      unbind_node = f"{drv_path}/unbind"
      print(f"Unbinding {gpu} from current driver {driver_name} (writing to {unbind_node})...")
      try:
        with open(unbind_node, "w") as f:
          f.write(gpu)
        time.sleep(0.5)
      except Exception as e:
        print(f"Failed to unbind {gpu}: {e}")

    # 2. Trigger Function Level Reset (FLR)
    reset_path = f"{dev_path}/reset"
    flr_success = False
    if FileIOInterface.exists(reset_path):
      print(f"Triggering Function Level Reset (FLR) (writing 1 to {reset_path})...")
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
          if header and header != b'\xff\xff\xff\xff':
            config_responsive = True
      except Exception:
        pass

    if not flr_success or not config_responsive:
      print("Device is unresponsive or FLR failed. Triggering PCI bus remove & rescan...")
      
      remove_path = f"{dev_path}/remove"
      if FileIOInterface.exists(remove_path):
        print(f"Removing device from PCI tree (writing 1 to {remove_path})...")
        try:
          with open(remove_path, "w") as f:
            f.write("1")
          time.sleep(1.0)
        except Exception as e:
          print(f"Failed to remove device: {e}")

      rescan_path = "/sys/bus/pci/rescan"
      if FileIOInterface.exists(rescan_path):
        print(f"Rescanning PCI bus (writing 1 to {rescan_path})...")
        try:
          with open(rescan_path, "w") as f:
            f.write("1")
          time.sleep(2.0)
        except Exception as e:
          print(f"Failed to trigger PCI bus rescan: {e}")

    # 4. Check if the device is visible after rescan/reset
    if not FileIOInterface.exists(dev_path):
      print(f"Error: Device {gpu} did not reappear after reset/rescan!")
      continue

    # Unbind from any auto-bound driver after rescan
    current_drv_link = f"{dev_path}/driver"
    if FileIOInterface.exists(current_drv_link):
      current_drv = os.path.basename(os.readlink(current_drv_link))
      if current_drv != "vfio-pci":
        unbind_node = f"{current_drv_link}/unbind"
        print(f"Device auto-bound to {current_drv} after rescan. Unbinding from {current_drv} (writing to {unbind_node})...")
        try:
          with open(unbind_node, "w") as f:
            f.write(gpu)
          time.sleep(0.5)
        except Exception as e:
          print(f"Failed to unbind from {current_drv}: {e}")

    # 5. Bind to vfio-pci
    vfio_bind_path = "/sys/bus/pci/drivers/vfio-pci/bind"
    if FileIOInterface.exists(vfio_bind_path):
      override_path = f"{dev_path}/driver_override"
      try:
        print(f"Writing 'vfio-pci' to {override_path}...")
        with open(override_path, "w") as f:
          f.write("vfio-pci")
        
        current_drv_link = f"{dev_path}/driver"
        is_already_bound = False
        if FileIOInterface.exists(current_drv_link):
          if os.path.basename(os.readlink(current_drv_link)) == "vfio-pci":
            is_already_bound = True

        if not is_already_bound:
          print(f"Binding {gpu} to vfio-pci by writing to {vfio_bind_path}...")
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
        # Print dmesg log to help debug
        print("\n--- Kernel logs (dmesg) regarding the failure ---")
        run_cmd("dmesg | tail -n 25")
    else:
      print("Error: vfio-pci driver bind path not found. Is vfio-pci module loaded?")
