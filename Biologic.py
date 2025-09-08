import os, sys, time
from enum import Enum
from threading import Lock
from contextlib import AbstractContextManager

# --- EC-Lab SDK ---
from kbio.kbio_api import KBIO_api
from kbio.kbio_types import PROG_STATE
from kbio.utils import exception_brief
from kbio.kbio_tech import ECC_parm, make_ecc_parm, make_ecc_parms, get_experiment_data, get_info_data

# ---------- helpers: find cp.ecc ----------
COMMON_TECH_HINTS = [
    r"C:\Program Files (x86)\EC-Lab",
    r"C:\Program Files\EC-Lab",
    r"C:\Users\Public\Documents\EC-Lab",
    r"C:\Program Files (x86)\EC-Lab Development Package",
]

def find_cp_ecc() -> str | None:
    # 1) allow override via env var
    env_dir = os.environ.get("ECLAB_TECH_DIR")
    if env_dir:
        p = os.path.join(env_dir, "cp.ecc")
        if os.path.isfile(p):
            print(f"[ECC] Using cp.ecc from ECLAB_TECH_DIR: {p}")
            return p

    # 2) allow simple hardcode (edit this if you already know it)
    HARDCODE = r"C:\Program Files (x86)\EC-Lab\EC-Lab 11.50\techniques\cp.ecc"
    if os.path.isfile(HARDCODE):
        print(f"[ECC] Using cp.ecc (hardcoded): {HARDCODE}")
        return HARDCODE

    # 3) walk common roots
    candidates = []
    for root in COMMON_TECH_HINTS:
        if os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                if "cp.ecc" in filenames:
                    candidates.append(os.path.join(dirpath, "cp.ecc"))
    if candidates:
        # pick the first; you can refine if multiple
        print("[ECC] Found candidates:")
        for c in candidates:
            print("       ", c)
        print(f"[ECC] Using: {candidates[0]}")
        return candidates[0]

    return None

# ---------- simple interface ----------
class ChargeState(Enum):
    IDLE = 0
    CHARGING = 1
    DISCHARGING = 2

class BioLogicInterface(AbstractContextManager):
    CP_PARAMS = {
        "current":         ECC_parm("I", float),
        "duration":        ECC_parm("Duration", float),
        "record_interval": ECC_parm("Record_every_dE", float),
        "voltage_limit":   ECC_parm("Ew_limit", float),
        "timebase":        ECC_parm("tb", int),
    }

    def __init__(self, eclib_dll_path, blfind_dll_path=None):
        self.api = KBIO_api(eclib_file=eclib_dll_path, blfind_file=blfind_dll_path)
        self.connection_id = None
        self.connected = False
        self._lock = Lock()

    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): self.shutdown()

    def connect(self, address, timeout_s=5):
        try:
            print(f"Connecting to {address} ...")
            self.connection_id, _ = self.api.Connect(address, timeout_s)
            self.connected = True
            print("Connected successfully to BioLogic device.")
            return True
        except Exception as e:
            print("Connection error:", exception_brief(e, extended=True))
            return False

    def disconnect(self):
        if self.connected:
            self.api.Disconnect(self.connection_id)
            self.connected = False
            self.connection_id = None
            print("Disconnected from instrument")

    def shutdown(self):
        if self.connected:
            try:
                for ch in range(1, 17):
                    try: self.api.StopChannel(self.connection_id, ch)
                    except: pass
                self.disconnect()
            except: pass

    def load_cp_technique(self, channel, current, duration, record_interval, voltage_limit, cp_path):
        if not self.connected: raise RuntimeError("Not connected")
        try:
            params = [
                make_ecc_parm(self.api, self.CP_PARAMS["current"],         current),
                make_ecc_parm(self.api, self.CP_PARAMS["duration"],        duration),
                make_ecc_parm(self.api, self.CP_PARAMS["record_interval"], record_interval),
                make_ecc_parm(self.api, self.CP_PARAMS["voltage_limit"],   voltage_limit),
            ]
            params = make_ecc_parms(self.api, *params)
            self.api.LoadTechnique(self.connection_id, channel, cp_path, params)
            return True
        except Exception as e:
            print("Error loading CP technique:", exception_brief(e, extended=True))
            return False

    def start_channel(self, channel):
        self.api.StartChannel(self.connection_id, channel)
        print(f"Channel {channel} started")

    def stop_channel(self, channel):
        self.api.StopChannel(self.connection_id, channel)
        print(f"Channel {channel} stopped")

    def get_experiment_samples(self, channel):
        data = self.api.GetData(self.connection_id, channel)
        status, tech = get_info_data(self.api, data)
        # board type isn’t needed for reading generic fields here
        samples = list(get_experiment_data(self.api, data, tech, None))
        return status, tech, samples

# ---------- one-cycle CP (charge→discharge) ----------
def run_cp_cycle(bio, channel, charge_current, discharge_current,
                 cutoff_voltage, duration, record_interval, output_file, cp_ecc_path):
    if not os.path.isfile(cp_ecc_path):
        raise FileNotFoundError(
            f"cp.ecc not found at:\n  {cp_ecc_path}\n\n"
            "Fix it by one of:\n"
            "  • Install the full EC-Lab software and point TECH dir correctly\n"
            "  • Set ECLAB_TECH_DIR env var to the folder that contains cp.ecc\n"
            "  • Hardcode cp.ecc path in this script\n"
        )

    chg_I = abs(charge_current)
    dchg_I = -abs(discharge_current)

    with open(output_file, "w", newline="") as f:
        f.write("Cycle,Phase,Time(s),Voltage(V),Current(A),State\n")

        print("\nStarting cycle 1 of 1")
        # CHARGE
        print("Starting charge phase...")
        if not bio.load_cp_technique(channel, chg_I, duration, record_interval, cutoff_voltage, cp_ecc_path):
            raise RuntimeError("CP load failed for charge (bad cp.ecc path or version mismatch)")
        bio.start_channel(channel)
        _phase_loop(bio, channel, "Charge", cutoff_voltage, f, 1)

        time.sleep(0.3)

        # DISCHARGE (use a lower cutoff)
        lower_cut = cutoff_voltage - 1.0
        print("Starting discharge phase...")
        if not bio.load_cp_technique(channel, dchg_I, duration, record_interval, lower_cut, cp_ecc_path):
            raise RuntimeError("CP load failed for discharge (bad cp.ecc path or version mismatch)")
        bio.start_channel(channel)
        _phase_loop(bio, channel, "Discharge", lower_cut, f, 1)

    print(f"Data saved to {output_file}")

def _phase_loop(bio, channel, phase, vcut, f, cyc_idx):
    while True:
        status, _, samples = bio.get_experiment_samples(channel)
        for s in samples:
            t = s.get("t", 0.0)
            v = s.get("Ewe", 0.0)
            cur = s.get("I", s.get("Iwe", 0.0))
            state = "CHARGING" if cur > 0.01 else ("DISCHARGING" if cur < -0.01 else "IDLE")
            f.write(f"{cyc_idx},{phase},{t},{v},{cur},{state}\n"); f.flush()

            if phase == "Charge" and v >= vcut:
                print(f"Charge complete: reached {vcut} V")
                bio.stop_channel(channel)
                return
            if phase == "Discharge" and v <= vcut:
                print(f"Discharge complete: reached {vcut} V")
                bio.stop_channel(channel)
                return

        if status == "STOP":
            print(f"{phase} complete: technique finished")
            return
        time.sleep(0.25)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    # Your DLLs (keep versions aligned with installed EC-Lab!)
    ECLIB_PATH  = r"C:\Program Files (x86)\EC-Lab Development Package\lib\EClib64.dll"
    BLFIND_PATH = r"C:\Program Files (x86)\EC-Lab Development Package\lib\blfind64.dll"

    DEVICE_ADDRESS = "192.109.209.128"
    OUTPUT_FILE    = "cp_test_data.csv"

    cp_ecc = find_cp_ecc()
    if not cp_ecc:
        print(
            "Could not locate cp.ecc automatically.\n"
            "Fix it by one of:\n"
            "  • Install the full EC-Lab software (not just Dev Package)\n"
            "  • Set environment variable ECLAB_TECH_DIR to the folder containing cp.ecc\n"
            "  • Edit HARDCODE in find_cp_ecc() to the actual cp.ecc path\n"
        )
        sys.exit(2)

    with BioLogicInterface(ECLIB_PATH, BLFIND_PATH) as bio:
        if not bio.connect(DEVICE_ADDRESS):
            sys.exit(1)
        # Pick channel 1 (or detect via your own helper)
        channel = 1

        run_cp_cycle(
            bio,
            channel=channel,
            charge_current=0.005,
            discharge_current=-0.005,
            cutoff_voltage=4.3,
            duration=60,
            record_interval=0.5,
            output_file=OUTPUT_FILE,
            cp_ecc_path=cp_ecc,
        )
