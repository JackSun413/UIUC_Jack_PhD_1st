#####################################################################
# Bio-Logic OEM Package — minimal multi-tech sequence (PEIS + CC)
# Based on your working demo; adds:
#   • PEIS phases (before charge, after charge, after discharge)
#   • Constant-current charge/discharge with software V cutoffs
#   • GC loop (charge/discharge pairs)
#   • Single CSV with Phase column + capacity at every sample
#####################################################################

import os
import sys
import time
from dataclasses import dataclass

import kbio.kbio_types as KBIO
from kbio.c_utils import c_is_64b
from kbio.kbio_api import KBIO_api
from kbio.kbio_tech import (
    ECC_parm, get_experiment_data, get_info_data,
    make_ecc_parm, make_ecc_parms
)
from kbio.utils import exception_brief

# ================= USER CONFIG =================
verbosity = 2

# Set your *current* instrument address here (works with your updated Dev Package)
address      = "192.109.209.128"      # <--- EDIT if your new IP differs
channel      = 1
binary_path  = r"C:\EC-Lab Development Package\lib"   # your updated Dev Package
force_load_firmware = False

# ECC files in your Dev Package \lib
peis_tech_file = rf"{binary_path}\peis.ecc"
cp3_tech_file  = rf"{binary_path}\cp.ecc"
cp4_tech_file  = rf"{binary_path}\cp4.ecc"
cp5_tech_file  = rf"{binary_path}\cp5.ecc"

# Output
csv_path = "sequence.csv"

# ---- Protocol setpoints (edit as needed) ----
# PEIS (single-sine)
PEIS_fi_Hz = 1e6
PEIS_ff_Hz = 1.0
PEIS_pts_per_dec = 6
PEIS_amp_mV = 10.0
PEIS_pw = 0.10
PEIS_nav = 2
PEIS_bw  = 5

# CC (constant-current via CP*.ecc single-step; software V cutoffs)
I_charge_A   = +0.050e-3  # +50 µA
I_discharge_A= -0.050e-3  # -50 µA
I_loop_A     = +0.057e-3  # +57 µA for loop charge; discharge uses negative
Vmax_cut_V   = 4.30
Vmin_cut_V   = 2.50
record_dt_s  = 10.0       # if CP ECC supports Record_every_dT
record_dE_V  = 0.005      # if CP ECC supports Record_every_dE
cp_step_dur_s= 5*3600     # long step; software cut will end sooner
loop_pairs   = 4          # number of (charge, discharge) pairs in the loop
i_range_key  = "I_RANGE_1mA"  # or "I_RANGE_10mA" etc., depending on your cell

# ==================================================

def newline(): print()

def print_exception(e):
    print(f"{exception_brief(e, verbosity>=2)}")

# ===== CP parameter descriptors (as in your working demo) =====
CP_parms = {
    "current_step": ECC_parm("Current_step", float),
    "step_duration": ECC_parm("Duration_step", float),
    "vs_init": ECC_parm("vs_initial", bool),
    "nb_steps": ECC_parm("Step_number", int),
    "record_dt": ECC_parm("Record_every_dT", float),
    "record_dE": ECC_parm("Record_every_dE", float),
    "repeat": ECC_parm("N_Cycles", int),
    "I_range": ECC_parm("I_Range", int),
}

# ===== PEIS parameter descriptors (typical names) =====
PEIS_parms = {
    "fi":        ECC_parm("fi", float),
    "ff":        ECC_parm("ff", float),
    "Nd":        ECC_parm("Nd", int),
    "Va":        ECC_parm("Va", float),
    "pw":        ECC_parm("pw", float),
    "Na":        ECC_parm("Na", int),
    "Bandwidth": ECC_parm("Bandwidth", int),
    "record":    ECC_parm("record", int),
}

@dataclass
class current_step:
    current: float
    duration: float
    vs_init: bool = False

def build_cp_params(api, steps, repeat_count, record_dt=None, record_dE=None, i_range_name=None):
    """Build CP EccParams compatible with cp*.ecc using your working pattern."""
    p_list = []
    last_idx = 0
    for idx, st in enumerate(steps):
        p_list.append(make_ecc_parm(api, CP_parms["current_step"], st.current, idx))
        p_list.append(make_ecc_parm(api, CP_parms["step_duration"], st.duration, idx))
        p_list.append(make_ecc_parm(api, CP_parms["vs_init"], st.vs_init, idx))
        last_idx = idx

    # Step_number is "number of steps – 1" (as in your demo)
    p_list.append(make_ecc_parm(api, CP_parms["nb_steps"], last_idx))

    if record_dt is not None:
        p_list.append(make_ecc_parm(api, CP_parms["record_dt"], record_dt))
    if record_dE is not None:
        p_list.append(make_ecc_parm(api, CP_parms["record_dE"], record_dE))
    if i_range_name:
        p_list.append(make_ecc_parm(api, CP_parms["I_range"], KBIO.I_RANGE[i_range_name].value))

    p_list.append(make_ecc_parm(api, CP_parms["repeat"], repeat_count))
    return make_ecc_parms(api, *p_list)

def build_peis_params(api):
    """Build PEIS EccParams (non-empty) with the standard fields."""
    p_list = [
        make_ecc_parm(api, PEIS_parms["fi"], PEIS_fi_Hz),
        make_ecc_parm(api, PEIS_parms["ff"], PEIS_ff_Hz),
        make_ecc_parm(api, PEIS_parms["Nd"], PEIS_pts_per_dec),
        make_ecc_parm(api, PEIS_parms["Va"], PEIS_amp_mV),
        make_ecc_parm(api, PEIS_parms["pw"], PEIS_pw),
        make_ecc_parm(api, PEIS_parms["Na"], PEIS_nav),
        make_ecc_parm(api, PEIS_parms["Bandwidth"], PEIS_bw),
        make_ecc_parm(api, PEIS_parms["record"], 0),
    ]
    return make_ecc_parms(api, *p_list)

def integrate_trap(prev_q_mAh, i_prev, i_cur, dt_s):
    return prev_q_mAh + ((i_prev + i_cur) * 0.5 * dt_s) * 1000.0 / 3600.0

def run_peis(api, id_, ch, board_type, phase_name, csvf):
    """Load + run PEIS; log every point; capacity integrates continuously."""
    parms = build_peis_params(api)
    api.LoadTechnique(id_, ch, peis_tech_file, parms, first=True, last=True, display=(verbosity>1))
    api.StartChannel(id_, ch)

    # We’ll integrate capacity across the whole run; carry state in outer scope via closure
    run_peis.q_mAh = getattr(run_peis, "q_mAh", 0.0)
    run_peis.last_t = getattr(run_peis, "last_t", None)
    run_peis.last_I = getattr(run_peis, "last_I", None)

    print(f"> [{phase_name}] Reading data ", end="", flush=True)
    while True:
        data = api.GetData(id_, ch)
        status, tech_name = get_info_data(api, data)
        print(".", end="", flush=True)

        for out in get_experiment_data(api, data, tech_name, board_type):
            t  = out.get("t", 0.0)
            Ew = out.get("Ewe", 0.0)
            Iw = out.get("Iwe", 0.0)

            if run_peis.last_t is None:
                dt = 0.0
            else:
                dt = max(0.0, t - run_peis.last_t)
            i_prev = Iw if run_peis.last_I is None else run_peis.last_I
            run_peis.q_mAh = integrate_trap(run_peis.q_mAh, i_prev, Iw, dt)
            run_peis.last_t, run_peis.last_I = t, Iw

            # Write row (include freq/Z if present)
            freq = out.get("freq")
            zre  = out.get("Zre")
            zim  = out.get("Zim")
            csvf.write(f"{phase_name},{t},{Ew},{Iw},{run_peis.q_mAh}")
            if freq is not None: csvf.write(f",{freq}")
            else:                 csvf.write(",")
            if zre  is not None: csvf.write(f",{zre}")
            else:                 csvf.write(",")
            if zim  is not None: csvf.write(f",{zim}")
            else:                 csvf.write(",")
            csvf.write("\n")

        if status == "STOP":
            print()  # newline after dots
            break

        time.sleep(0.2)

def run_cc_with_vcut(api, id_, ch, board_type, phase_name, I_A, vcut, tech_file, csvf):
    """
    Run a *single-step* constant-current using cp*.ecc and stop at software voltage limit.
    """
    steps = [current_step(I_A, cp_step_dur_s, False)]  # one long step; software will stop sooner
    parms = build_cp_params(api, steps, repeat_count=1, record_dt=record_dt_s, record_dE=record_dE_V, i_range_name=i_range_key)
    api.LoadTechnique(id_, ch, tech_file, parms, first=True, last=True, display=(verbosity>1))
    api.StartChannel(id_, ch)

    # carry capacity integration state across entire run
    run_cc_with_vcut.q_mAh = getattr(run_cc_with_vcut, "q_mAh", getattr(run_peis, "q_mAh", 0.0))
    run_cc_with_vcut.last_t = getattr(run_cc_with_vcut, "last_t", getattr(run_peis, "last_t", None))
    run_cc_with_vcut.last_I = getattr(run_cc_with_vcut, "last_I", getattr(run_peis, "last_I", None))

    print(f"> [{phase_name}] Reading data ", end="", flush=True)
    while True:
        data = api.GetData(id_, ch)
        status, tech_name = get_info_data(api, data)
        print(".", end="", flush=True)

        for out in get_experiment_data(api, data, tech_name, board_type):
            t  = out.get("t", 0.0)
            Ew = out.get("Ewe", 0.0)
            Iw = out.get("Iwe", 0.0)

            if run_cc_with_vcut.last_t is None:
                dt = 0.0
            else:
                dt = max(0.0, t - run_cc_with_vcut.last_t)
            i_prev = Iw if run_cc_with_vcut.last_I is None else run_cc_with_vcut.last_I
            run_cc_with_vcut.q_mAh = integrate_trap(run_cc_with_vcut.q_mAh, i_prev, Iw, dt)
            run_cc_with_vcut.last_t, run_cc_with_vcut.last_I = t, Iw

            # write CSV row (no Z during CC)
            csvf.write(f"{phase_name},{t},{Ew},{Iw},{run_cc_with_vcut.q_mAh},,,\n")

            # software cutoff
            if (Iw > 0 and Ew >= vcut) or (Iw < 0 and Ew <= vcut):
                print(f"\n> [{phase_name}] Reached cutoff {vcut:.3f} V → stopping channel")
                api.StopChannel(id_, ch)
                return

        if status == "STOP":
            print()  # newline
            break

        time.sleep(0.2)

# =============================== MAIN ===============================
try:
    newline()

    # Pick DLL
    DLL_file = "EClib64.dll" if c_is_64b else "EClib.dll"
    DLL_path = f"{binary_path}{os.sep}{DLL_file}"

    # API
    api = KBIO_api(DLL_path)

    # Library version
    version = api.GetLibVersion()
    print(f"> EcLib version: {version}")
    newline()

    # Connect
    id_, device_info = api.Connect(address)
    print(f"> device[{address}] info :")
    print(device_info)
    newline()

    # Board type -> firmware + CP ecc
    board_type = api.GetChannelBoardType(id_, channel)
    if board_type == KBIO.BOARD_TYPE.ESSENTIAL.value:
        firmware_path = "kernel.bin";   fpga_path = "Vmp_ii_0437_a6.xlx"; tech_file = cp3_tech_file
    elif board_type == KBIO.BOARD_TYPE.PREMIUM.value:
        firmware_path = "kernel4.bin";  fpga_path = "vmp_iv_0395_aa.xlx";  tech_file = cp4_tech_file
    elif board_type == KBIO.BOARD_TYPE.DIGICORE.value:
        firmware_path = "kernel.bin";   fpga_path = "";                    tech_file = cp5_tech_file
    else:
        print("> Board type detection failed")
        sys.exit(-1)

    # Load firmware (as in your working demo)
    print(f"> Loading {firmware_path} ...")
    channel_map = api.channel_map({channel})
    api.LoadFirmware(id_, channel_map, firmware=firmware_path, fpga=fpga_path, force=force_load_firmware)
    print("> ... firmware loaded")
    newline()

    # Channel info
    channel_info = api.GetChannelInfo(id_, channel)
    print(f"> Channel {channel} info :")
    print(channel_info)
    newline()

    if not channel_info.is_kernel_loaded:
        print("> kernel must be loaded in order to run the experiment")
        sys.exit(-1)

    # Quick checks
    if not os.path.isfile(peis_tech_file):
        raise FileNotFoundError(f"Missing PEIS technique file: {peis_tech_file}")
    if not os.path.isfile(tech_file):
        raise FileNotFoundError(f"Missing CP technique file for this board: {tech_file}")

    # Open CSV
    csvfile = open(csv_path, "w", buffering=1)  # line-buffer
    csvfile.write("Phase,Time(s),Ewe(V),Iwe(A),Capacity(mAh),freq(Hz),Zre(Ohm),Zim(Ohm)\n")

    # --------- SEQUENCE ---------
    # 1) PEIS 1 @ OCV
    run_peis(api, id_, channel, board_type, "PEIS 1", csvfile)

    # 2) Constant-current Charge to Vmax (software cut)
    run_cc_with_vcut(api, id_, channel, board_type, "CC Charge", I_charge_A, Vmax_cut_V, tech_file, csvfile)

    # 3) PEIS 2 (top-of-charge)
    run_peis(api, id_, channel, board_type, "PEIS 2", csvfile)

    # 4) Constant-current Discharge to Vmin (software cut)
    run_cc_with_vcut(api, id_, channel, board_type, "CC Discharge", I_discharge_A, Vmin_cut_V, tech_file, csvfile)

    # 5) PEIS 3 (after discharge)
    run_peis(api, id_, channel, board_type, "PEIS 3", csvfile)

    # 6) Loop pairs (charge→discharge)
    for cyc in range(1, loop_pairs + 1):
        run_cc_with_vcut(api, id_, channel, board_type, f"Loop Charge {cyc}", +I_loop_A, Vmax_cut_V, tech_file, csvfile)
        run_cc_with_vcut(api, id_, channel, board_type, f"Loop Disch {cyc}",  -I_loop_A, Vmin_cut_V, tech_file, csvfile)

    csvfile.close()
    print(f"\n> Sequence done. Data saved to {csv_path}")

    # Disconnect
    api.Disconnect(id_)

except KeyboardInterrupt:
    print(".. interrupted")
    try:
        csvfile.close()
    except Exception:
        pass

except Exception as e:
    try:
        csvfile.close()
    except Exception:
        pass
    print_exception(e)
