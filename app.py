"""
KALKULATOR GEOMETRI TIKUNGAN JALAN  (FC - SCS - SS)
Streamlit + ezdxf + pandas/openpyxl

Jalankan :  streamlit run app.py
Install  :  pip install streamlit ezdxf pandas numpy openpyxl matplotlib
"""
import base64
import io
import math
import re

import numpy as np
import pandas as pd
import streamlit as st
import ezdxf

try:
    from ezdxf.enums import TextEntityAlignment

    def _align(a):
        return TextEntityAlignment[a]
except Exception:  # ezdxf versi lama
    def _align(a):
        return a

# =============================================================================
#  KONSTANTA STANDAR
# =============================================================================
# Radius minimum tikungan FC tanpa lengkung peralihan (Bina Marga / TPGJAK)
RMIN_FC = {120: 2500, 100: 1500, 80: 900, 60: 500, 50: 350, 40: 250, 30: 130, 20: 60}
# Jarak pandang mendahului minimum (TPGJAK No. 038/TBM/1997)
JPM_STD = {120: 800, 100: 670, 80: 550, 60: 350, 50: 250, 40: 200, 30: 150, 20: 100}
# Jarak pandang henti minimum (Bina Marga)
JPH_STD = {120: 250, 100: 175, 80: 120, 60: 75, 50: 55, 40: 40, 30: 27, 20: 16}

D2R = math.pi / 180.0
R2D = 180.0 / math.pi


def _nearest(tabel, v):
    return tabel[min(tabel, key=lambda k: abs(k - v))]


def fmt_sta(x):
    """Format stasioning:  385.0 -> 0+385.00"""
    return f"{int(x // 1000)}+{x % 1000:06.2f}"


def baris(nama, simbol, rumus, nilai, satuan):
    return {"Parameter": nama, "Simbol": simbol, "Rumus": rumus, "Nilai": nilai, "Satuan": satuan}


# =============================================================================
#  PERHITUNGAN DASAR
# =============================================================================
def f_gesek(vr):
    """Koefisien gesek melintang maksimum."""
    return -0.00065 * vr + 0.192 if vr < 80 else -0.00125 * vr + 0.24


def hitung_dasar(P):
    f = f_gesek(P["Vr"])
    rmin = P["Vr"] ** 2 / (127 * (P["emax"] + f))
    return {"f": f, "Rmin": rmin, "R_ok": P["Rc"] >= rmin, "RminFC": _nearest(RMIN_FC, P["Vr"])}


def ls_kriteria(P):
    """Empat kriteria panjang lengkung peralihan minimum (sesuai laporan)."""
    vr, R = P["Vr"], P["Rc"]
    re = P["re"] if P["re"] > 0 else (0.025 if vr <= 70 else 0.035)
    k1 = 0.0214 * vr ** 3 / (R * P["C1"])
    k2 = vr / 3.6 * P["T"]
    k3 = 0.022 * vr ** 3 / (R * P["Cc"]) - 2.727 * vr * P["emax"] / P["Cc"]
    k4 = (P["emax"] - P["en"]) * vr / (3.6 * re)
    return k1, k2, k3, k4, re


# ----------------------------------------------------------------- FULL CIRCLE
def hitung_fc(P, sta_pi):
    R, d = P["Rc"], P["delta"]
    dasar = hitung_dasar(P)
    Lc = d * math.pi * R / 180
    Tc = R * math.tan(d / 2 * D2R)
    Ec = Tc * math.tan(d / 4 * D2R)
    v = dict(R=R, delta=d, Lc=Lc, Tc=Tc, Ec=Ec)
    ok = dasar["R_ok"]
    pesan = []
    if not dasar["R_ok"]:
        pesan.append(f"R = {R:.2f} m < Rmin = {dasar['Rmin']:.2f} m (tidak memenuhi).")
    if R < dasar["RminFC"]:
        pesan.append(
            f"R < {dasar['RminFC']} m (R minimum FC tanpa lengkung peralihan untuk Vr ini). "
            "FC tetap dihitung, tetapi sebaiknya gunakan SCS/SS."
        )
    rows = [
        baris("Koefisien gesek", "f", "-0,00065·Vr + 0,192 (Vr<80); -0,00125·Vr + 0,24", dasar["f"], "-"),
        baris("Radius minimum", "Rmin", "Vr² / [127(emax + f)]", dasar["Rmin"], "m"),
        baris("Cek radius rencana", "Rc ≥ Rmin", f"{R:g} ≥ {dasar['Rmin']:.2f}", "OK" if dasar["R_ok"] else "TIDAK OK", "-"),
        baris("Panjang busur lingkaran", "Lc", "Δ·2π·R / 360", Lc, "m"),
        baris("Jarak TC ke PI", "Tc", "R·tan(Δ/2)", Tc, "m"),
        baris("Jarak PI ke busur", "Ec", "Tc·tan(Δ/4)", Ec, "m"),
    ]
    sta = [
        ("TC (awal tikungan)", sta_pi - Tc),
        ("PI", sta_pi),
        ("CT (akhir tikungan)", sta_pi - Tc + Lc),
    ]
    return dict(tipe="FC", ok=ok, pesan=pesan, v=v, rows=rows, sta=sta)


# ------------------------------------------------------- SPIRAL-CIRCLE-SPIRAL
def _spiral_umum(R, d, Ls, tipe, P, sta_pi):
    """Rumus bersama SCS & SS untuk Ls dan theta_s yang sudah diketahui."""
    ths = 90 * Ls / (math.pi * R) if tipe == "SCS" else d / 2
    thc = d - 2 * ths
    Lc = thc * math.pi * R / 180 if thc > 0 else 0.0
    Xc = Ls - Ls ** 3 / (40 * R ** 2)
    Yc = Ls ** 2 / (6 * R)
    p = Yc - R * (1 - math.cos(ths * D2R))
    k = Xc - R * math.sin(ths * D2R)
    Es = (R + p) / math.cos(d / 2 * D2R) - R
    Ts = (R + p) * math.tan(d / 2 * D2R) + k
    Ltot = Lc + 2 * Ls
    return dict(R=R, delta=d, Ls=Ls, ths=ths, thc=thc, Lc=Lc, Xc=Xc, Yc=Yc, P=p, K=k, Es=Es, Ts=Ts, Ltot=Ltot)


def hitung_scs(P, sta_pi):
    R, d = P["Rc"], P["delta"]
    dasar = hitung_dasar(P)
    k1, k2, k3, k4, re = ls_kriteria(P)
    ls_min = max(k1, k2, k3, k4)
    ls = P["Ls_rencana"] if P["Ls_rencana"] > 0 else math.ceil(ls_min / 5) * 5
    v = _spiral_umum(R, d, ls, "SCS", P, sta_pi)
    pesan, ok = [], dasar["R_ok"]
    if not dasar["R_ok"]:
        pesan.append(f"R = {R:.2f} m < Rmin = {dasar['Rmin']:.2f} m (tidak memenuhi).")
    if ls < ls_min:
        pesan.append(f"Ls rencana {ls:.2f} m < Ls min {ls_min:.2f} m.")
        ok = False
    if v["thc"] <= 0:
        pesan.append(f"θc = {v['thc']:.2f}° ≤ 0 → SCS tidak bisa dibentuk, gunakan SS.")
        ok = False
    elif v["Lc"] < 20:
        pesan.append(f"Lc = {v['Lc']:.2f} m < 20 m → disarankan memakai SS.")
    rows = [
        baris("Koefisien gesek", "f", "-0,00065·Vr + 0,192 (Vr<80); -0,00125·Vr + 0,24", dasar["f"], "-"),
        baris("Radius minimum", "Rmin", "Vr² / [127(emax + f)]", dasar["Rmin"], "m"),
        baris("Ls min kriteria 1 (Shortt)", "Ls₁", "0,0214·Vr³ / (R·C)", k1, "m"),
        baris("Ls min kriteria 2 (waktu tempuh)", "Ls₂", "Vr/3,6 · T", k2, "m"),
        baris("Ls min kriteria 3 (gaya sentrifugal)", "Ls₃", "0,022·Vr³/(R·C) − 2,727·Vr·e/C", k3, "m"),
        baris("Ls min kriteria 4 (landai relatif)", "Ls₄", "(emax − en)·Vr / (3,6·re)", k4, "m"),
        baris("Ls minimum (terbesar)", "Ls min", "max(Ls₁..Ls₄)", ls_min, "m"),
        baris("Ls rencana", "Ls", "dibulatkan ke atas kelipatan 5" if P["Ls_rencana"] <= 0 else "input", ls, "m"),
        baris("Sudut spiral", "θs", "90·Ls / (π·R)", v["ths"], "°"),
        baris("Sudut busur lingkaran", "θc", "Δ − 2θs", v["thc"], "°"),
        baris("Panjang busur lingkaran", "Lc", "θc/360 · 2πR", v["Lc"], "m"),
        baris("Panjang total tikungan", "Ltot", "Lc + 2Ls", v["Ltot"], "m"),
        baris("Absis SC", "Xc", "Ls − Ls³/(40R²)", v["Xc"], "m"),
        baris("Ordinat SC", "Yc", "Ls²/(6R)", v["Yc"], "m"),
        baris("Pergeseran busur", "P", "Yc − R(1 − cos θs)", v["P"], "m"),
        baris("Absis pusat busur", "K", "Xc − R·sin θs", v["K"], "m"),
        baris("Jarak luar PI ke busur", "Es", "(R+P)/cos(Δ/2) − R", v["Es"], "m"),
        baris("Jarak TS ke PI", "Ts", "(R+P)·tan(Δ/2) + K", v["Ts"], "m"),
    ]
    ts = sta_pi - v["Ts"]
    sta = [
        ("TS (awal spiral)", ts),
        ("SC (spiral → busur)", ts + ls),
        ("PI", sta_pi),
        ("CS (busur → spiral)", ts + ls + v["Lc"]),
        ("ST (akhir spiral)", ts + 2 * ls + v["Lc"]),
    ]
    return dict(tipe="SCS", ok=ok, pesan=pesan, v=v, rows=rows, sta=sta)


# ------------------------------------------------------------- SPIRAL-SPIRAL
def hitung_ss(P, sta_pi):
    R, d = P["Rc"], P["delta"]
    dasar = hitung_dasar(P)
    k1, k2, k3, k4, re = ls_kriteria(P)
    ls_min = max(k1, k2, k3, k4)
    ths = d / 2
    ls = ths * math.pi * R / 90  # geometri SS: Ls ditentukan oleh Δ dan R
    v = _spiral_umum(R, d, ls, "SS", P, sta_pi)
    v["Lc"] = 0.0
    v["thc"] = 0.0
    v["Ltot"] = 2 * ls
    pesan, ok = [], dasar["R_ok"]
    if not dasar["R_ok"]:
        pesan.append(f"R = {R:.2f} m < Rmin = {dasar['Rmin']:.2f} m (tidak memenuhi).")
    if ls < ls_min:
        pesan.append(f"Ls = {ls:.2f} m < Ls min = {ls_min:.2f} m. Perbesar Δ / perkecil R, atau pakai FC/SCS.")
        ok = False
    rows = [
        baris("Koefisien gesek", "f", "-0,00065·Vr + 0,192 (Vr<80); -0,00125·Vr + 0,24", dasar["f"], "-"),
        baris("Radius minimum", "Rmin", "Vr² / [127(emax + f)]", dasar["Rmin"], "m"),
        baris("Sudut spiral", "θs", "Δ/2", ths, "°"),
        baris("Panjang spiral", "Ls", "θs·π·R / 90", ls, "m"),
        baris("Ls minimum (terbesar 4 kriteria)", "Ls min", "max(Ls₁..Ls₄)", ls_min, "m"),
        baris("Cek Ls ≥ Ls min", "-", f"{ls:.2f} ≥ {ls_min:.2f}", "OK" if ls >= ls_min else "TIDAK OK", "-"),
        baris("Absis SS", "Xs", "Ls − Ls³/(40R²)", v["Xc"], "m"),
        baris("Ordinat SS", "Ys", "Ls²/(6R)", v["Yc"], "m"),
        baris("Pergeseran busur", "P", "Ys − R(1 − cos θs)", v["P"], "m"),
        baris("Absis pusat busur", "K", "Xs − R·sin θs", v["K"], "m"),
        baris("Panjang total tikungan", "Ltot", "2·Ls", v["Ltot"], "m"),
        baris("Jarak luar PI ke busur", "Es", "(R+P)/cos(Δ/2) − R", v["Es"], "m"),
        baris("Jarak TS ke PI", "Ts", "(R+P)·tan(Δ/2) + K", v["Ts"], "m"),
    ]
    ts = sta_pi - v["Ts"]
    sta = [("TS (awal spiral)", ts), ("SS (titik spiral-spiral)", ts + ls), ("PI", sta_pi), ("ST (akhir spiral)", ts + 2 * ls)]
    return dict(tipe="SS", ok=ok, pesan=pesan, v=v, rows=rows, sta=sta)


def rekomendasi(P, hasil):
    """Saran jenis tikungan: FC bila R besar, SCS bila Lc ≥ 20 m, selain itu SS."""
    dasar = hitung_dasar(P)
    if P["Rc"] >= dasar["RminFC"] and hasil["FC"]["ok"]:
        return "FC"
    scs = hasil["SCS"]
    if scs["v"]["thc"] > 0 and scs["v"]["Lc"] >= 20 and scs["ok"]:
        return "SCS"
    return "SS"


# =============================================================================
#  SUPERELEVASI (diagram, putaran terhadap as jalan)
# =============================================================================
def e_rencana(P):
    """Superelevasi rencana cara Bina Marga (parabolik):  e = -emax·D²/Dmax² + 2·emax·D/Dmax
    dengan D = 1432,4/R dan Dmax = 181913,53·(emax+f)/Vr²."""
    f = f_gesek(P["Vr"])
    Dmax = 181913.53 * (P["emax"] + f) / P["Vr"] ** 2
    D = 1432.4 / P["Rc"]
    e = P["emax"] if D >= Dmax else -P["emax"] * D ** 2 / Dmax ** 2 + 2 * P["emax"] * D / Dmax
    return dict(Dmax=Dmax, D=D, e_auto=e)


def fp(v):
    """Format persen kemiringan: 0 ditampilkan tanpa tanda."""
    return "0.00%" if abs(v) < 5e-9 else f"{v:+.2f}%"


def _eo_ei(u, e, en, u1):
    """Kemiringan tepi luar dan tepi dalam (desimal, + naik terhadap as) pada fraksi pencapaian u (0..1).
    Tepi luar naik linier dari -en ke +e. Tepi dalam tetap -en sampai tepi luar mencapai +en (u1), lalu turun ke -e."""
    outer = -en + (e + en) * u
    if u <= u1 or u1 >= 1.0:
        inner = -en
    else:
        inner = -en - (e - en) * (u - u1) / (1.0 - u1)
    return outer, inner


def hitung_superelevasi(h, P, e_manual=0.0, p_tan=0.75, Ls_fc=0.0):
    """
    h        : hasil tikungan terpilih (FC / SCS / SS)
    e_manual : superelevasi manual (desimal); 0 = otomatis dari rumus Bina Marga
    p_tan    : porsi Ls' pada bagian lurus untuk FC (laporan/Bina Marga umumnya 3/4)
    Ls_fc    : Ls' fiktif FC (m); 0 = otomatis dari (e+en)·Vr / (3,6·re)
    """
    tipe, v, en, vr = h["tipe"], h["v"], P["en"], P["Vr"]
    es = e_rencana(P)
    pesan = []
    e = e_manual if e_manual > 0 else es["e_auto"]
    if e > P["emax"]:
        pesan.append(f"e rencana {e * 100:.2f}% melebihi e maks {P['emax'] * 100:.2f}%.")
    e = max(e, en)
    re_maks = P["re"] if P["re"] > 0 else (0.025 if vr <= 70 else 0.035)
    if tipe == "FC":
        L = Ls_fc if Ls_fc > 0 else (e + en) * vr / (3.6 * re_maks)
        xa1, xb2 = -p_tan * L, v["Lc"] + p_tan * L
        if v["Lc"] < 2 * (1 - p_tan) * L:
            pesan.append("Lc terlalu pendek: e penuh tidak tercapai di tengah busur (puncak diagram terpotong).")
    elif tipe == "SCS":
        L = v["Ls"]
        xa1, xb2 = 0.0, 2 * L + v["Lc"]
    else:
        L = v["Ls"]
        xa1, xb2 = 0.0, 2 * L
    u0, u1 = en / (e + en), min(2 * en / (e + en), 1.0)
    re_akt = (e + en) * vr / (3.6 * L) if L > 0 else float("inf")
    if re_akt > re_maks + 1e-9:
        pesan.append(f"Tingkat perubahan kemiringan {re_akt:.4f} m/m/det melebihi maks {re_maks:.3f}: perbesar Ls.")

    def u_at(x):
        return min(max((x - xa1) / L, 0.0), 1.0, max((xb2 - x) / L, 0.0))

    xs = set()
    for f_ in (0.0, u0, u1, 1.0):
        xs.add(round(xa1 + f_ * L, 9))
        xs.add(round(xb2 - f_ * L, 9))
    if xa1 + L > xb2 - L:
        xs.add(round((xa1 + xb2) / 2, 9))
    verts = []
    for x in sorted(xs):
        o, i = _eo_ei(u_at(x), e, en, u1)
        verts.append((x, round(o * 100, 9) + 0.0, round(i * 100, 9) + 0.0))

    sta0 = h["sta"][0][1]
    if tipe == "FC":
        titik = [("R1", xa1), ("TC", 0.0), ("R2", xa1 + L), ("R3", xb2 - L), ("CT", v["Lc"]), ("R4", xb2)]
    elif tipe == "SCS":
        titik = [("TS", 0.0), ("SC", L), ("CS", L + v["Lc"]), ("ST", 2 * L + v["Lc"])]
    else:
        titik = [("TS", 0.0), ("SS", L), ("ST", 2 * L)]
    titik = sorted({(round(x, 6), n) for n, x in titik})
    titik = [(n, x, sta0 + x) for x, n in titik]
    kunci = []
    for huruf, f_, ket in (("A", 0.0, "Normal"), ("B", u0, "Tepi luar 0%"), ("C", u1, "Tepi luar +en"), ("D", 1.0, "e penuh")):
        x = xa1 + f_ * L
        o, i = _eo_ei(f_, e, en, u1)
        kunci.append(dict(huruf=huruf, x=x, outer=round(o * 100, 9) + 0.0, inner=round(i * 100, 9) + 0.0, sta=sta0 + x, ket=ket))
    return dict(tipe=tipe, e=e, en=en, emax=P["emax"], L=L, xa1=xa1, xb2=xb2, u0=u0, u1=u1, p_tan=p_tan,
                re_akt=re_akt, re_maks=re_maks, es=es, verts=verts, titik=titik, kunci=kunci, pesan=pesan,
                x0=u0 * L, x1=u1 * L, sta0=sta0, e_manual=e_manual, Lc=v["Lc"])


# =============================================================================
#  PELEBARAN PERKERASAN
# =============================================================================
def hitung_pelebaran(P, R, vr):
    p, A, b, n, Bn, kz = P["p"], P["A"], P["b"], P["n"], P["Bn"], P["kz"]
    C = Bn / 2 - b
    b2 = R - math.sqrt(R ** 2 - p ** 2)
    bp = b + b2
    Td = math.sqrt(R ** 2 + A * (2 * p + A)) - R
    Z = kz * vr / math.sqrt(R)
    k_td = n + 1 if P["td_n_plus_1"] else n - 1  # laporan memakai (n+1); buku Bina Marga (n-1)
    Bt = n * (bp + C) + k_td * Td + Z
    db = Bt - Bn
    rows = [
        baris("Clearance samping", "C", "Bn/2 − b", C, "m"),
        baris("Off-tracking kendaraan", "b''", "R − √(R² − p²)", b2, "m"),
        baris("Lebar kendaraan di tikungan", "b'", "b + b''", bp, "m"),
        baris("Tonjolan depan kendaraan", "Td", "√(R² + A(2p + A)) − R", Td, "m"),
        baris("Faktor kesulitan mengemudi", "Z", f"{kz:g}·Vr / √R", Z, "m"),
        baris("Lebar perkerasan di tikungan", "Bt", "n(b'+C) + (n+1)·Td + Z" if P["td_n_plus_1"] else "n(b'+C) + (n−1)·Td + Z", Bt, "m"),
        baris("Kebutuhan pelebaran total", "Δb", "Bt − Bn", db, "m"),
        baris("Pelebaran per sisi", "Δb/2", "Δb / 2", db / 2, "m"),
    ]
    return dict(C=C, b2=b2, bp=bp, Td=Td, Z=Z, Bt=Bt, db=max(db, 0.0), db_raw=db, rows=rows)


# =============================================================================
#  JARAK PANDANG
# =============================================================================
def hitung_jph(vr, t, a, G):
    """G dalam desimal (+ tanjakan, - turunan)."""
    d1 = vr * t / 3.6
    d2 = vr ** 2 / (2 * 3.6 ** 2 * 9.81 * (a / 9.81 + G))
    return d1 + d2, d1, d2


def hitung_jpm(vr, m, d3):
    T1 = 2.12 + 0.026 * vr
    T2 = 6.56 + 0.048 * vr
    a = 2.052 + 0.0036 * vr
    d1 = 0.278 * T1 * (vr - m + a * T1 / 2)
    d2 = 0.278 * vr * T2
    d4 = 2 / 3 * d2
    return dict(T1=T1, T2=T2, a=a, d1=d1, d2=d2, d3=d3, d4=d4, JPM=d1 + d2 + d3 + d4)


# =============================================================================
#  GEOMETRI (koordinat lokal, satuan meter)
#  TS/TC di (0,0); tangen awal sepanjang +x; tikungan ke KIRI sebesar Δ.
# =============================================================================
def _spiral_pts(Ls, R, n=40):
    l = np.linspace(0, Ls, n)
    x = l - l ** 5 / (40 * R ** 2 * Ls ** 2)
    y = l ** 3 / (6 * R * Ls)
    return np.column_stack([x, y])


def _refleksi(pts, p0, u):
    v = np.asarray(pts, float) - p0
    dot = (v @ u)[..., None] if v.ndim > 1 else v @ u
    return p0 + 2 * dot * u - v


def bangun_geometri(hasil, ext, taper_fc=20.0):
    tipe, v = hasil["tipe"], hasil["v"]
    R, d = v["R"], v["delta"]
    cd, sd = math.cos(d * D2R), math.sin(d * D2R)
    g = {"tipe": tipe}
    if tipe == "FC":
        Ts = v["Tc"]
        O = np.array([0.0, R])
        PI = np.array([Ts, 0.0])
        ST = PI + Ts * np.array([cd, sd])
        a0, a1 = 270.0, 270.0 + d
        th = np.linspace(a0, a1, max(8, int(d / 2) + 8)) * D2R
        arc = O + R * np.column_stack([np.cos(th), np.sin(th)])
        s1 = s2 = None
        g.update(TC=np.array([0.0, 0.0]), CT=ST)
        curva = arc
        tcur = np.ones(len(arc))
    else:
        Ls, ths, thc, P_, K = v["Ls"], v["ths"], v["thc"], v["P"], v["K"]
        Ts = v["Ts"]
        O = np.array([K, R + P_])
        PI = np.array([Ts, 0.0])
        s1 = _spiral_pts(Ls, R)
        ts1 = np.linspace(0, 1, len(s1))
        u = (O - PI) / np.linalg.norm(O - PI)
        s2 = _refleksi(s1, PI, u)[::-1]
        ST = _refleksi(np.array([0.0, 0.0]), PI, u)
        SC = s1[-1]
        CS = s2[0]
        if thc > 1e-6:
            a0, a1 = 270.0 + ths, 270.0 + ths + thc
            th = np.linspace(a0, a1, max(8, int(thc / 2) + 8)) * D2R
            arc = O + R * np.column_stack([np.cos(th), np.sin(th)])
            curva = np.vstack([s1, arc[1:-1], s2])
            tcur = np.concatenate([ts1, np.ones(len(arc) - 2), ts1[::-1]])
        else:
            a0 = a1 = None
            arc = None
            curva = np.vstack([s1, s2[1:]])
            tcur = np.concatenate([ts1, ts1[::-1][1:]])
        g.update(TS=np.array([0.0, 0.0]), ST=ST, SC=SC, CS=CS)
    g.update(O=O, PI=PI, ST=ST, Ts=Ts, arc_ang=(a0, a1) if tipe == "FC" or v["thc"] > 1e-6 else None)

    # garis tengah lengkap (dengan perpanjangan tangen) + parameter pelebaran t (0..1)
    dirB = np.array([cd, sd])
    if tipe == "FC":  # pelebaran FC dibuat bertahap pada tangen sepanjang taper_fc
        pre = np.array([[-ext, 0.0], [-taper_fc, 0.0]])
        tpre = np.array([0.0, 0.0])
        post = np.array([ST + taper_fc * dirB, ST + ext * dirB])
        tpost = np.array([0.0, 0.0])
    else:
        pre = np.array([[-ext, 0.0]])
        tpre = np.array([0.0])
        post = np.array([ST + ext * dirB])
        tpost = np.array([0.0])
    center = np.vstack([pre, curva, post])
    tt = np.concatenate([tpre, tcur, tpost])
    g.update(center=center, t=tt, curva=curva, ext=ext, dirB=dirB, s1=s1, s2=s2)
    return g


def tepi_jalan(center, t, Bn, db):
    """Tepi kiri (sisi dalam, + pelebaran) dan tepi kanan jalan."""
    seg = np.diff(center, axis=0)
    seg = seg / np.maximum(np.linalg.norm(seg, axis=1)[:, None], 1e-12)
    nrm = np.column_stack([-seg[:, 1], seg[:, 0]])
    vn = np.zeros_like(center)
    vn[0], vn[-1] = nrm[0], nrm[-1]
    vn[1:-1] = nrm[:-1] + nrm[1:]
    vn /= np.maximum(np.linalg.norm(vn, axis=1)[:, None], 1e-12)
    kiri = center + vn * (Bn / 2 + db * t)[:, None]
    kanan = center - vn * (Bn / 2)
    return kiri, kanan


# =============================================================================
#  TRASE : JARAK, AZIMUT, SUDUT BELOK, STASIONING BERANTAI
# =============================================================================
def azimut(x1, y1, x2, y2):
    """Azimut (derajat, dari utara searah jarum jam). X = Easting, Y = Northing."""
    return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360


def sudut_belok(az1, az2):
    """Sudut belok Δ (positif) dan arah belok."""
    s = (az2 - az1 + 180) % 360 - 180
    return abs(s), ("Kanan" if s > 0 else "Kiri")


def nama_titik(i, n):
    return "A" if i == 0 else ("B" if i == n - 1 else f"PI-{i}")


def hitung_trase(rows, sta_awal, P0):
    """
    rows : list dict(X, Y, R, Vr, Jenis, Ls)  -> baris pertama = A, terakhir = B, tengah = PI
    P0   : parameter umum (emax, en, Cc, C1, T, re, p, A, b, n, Bn, kz, td_n_plus_1)

    STA PI(k) = STA ST(k-1) + d(k-1,k) - Ts(k-1)      (bukan jarak lurus kumulatif!)
    STA TS(k) = STA PI(k) - Ts(k);   STA ST(k) = STA TS(k) + Ltotal(k)
    """
    n = len(rows)
    out = dict(titik=[], ruas=[], pi=[], tabel_sta=[], peringatan=[], sta_akhir=None, panjang=None)
    if n < 2:
        return out
    out["titik"] = [(nama_titik(i, n), r["X"], r["Y"]) for i, r in enumerate(rows)]
    for i in range(n - 1):
        dx, dy = rows[i + 1]["X"] - rows[i]["X"], rows[i + 1]["Y"] - rows[i]["Y"]
        out["ruas"].append(dict(
            dari=nama_titik(i, n), ke=nama_titik(i + 1, n), dx=dx, dy=dy,
            d=math.hypot(dx, dy), az=azimut(rows[i]["X"], rows[i]["Y"], rows[i + 1]["X"], rows[i + 1]["Y"]),
        ))
    ts_list = [0.0] * n
    sta_st_prev, ts_prev = sta_awal, 0.0
    out["tabel_sta"].append(("A (awal trase)", sta_awal))
    for k in range(1, n - 1):
        r = rows[k]
        nama = nama_titik(k, n)
        sta_pi = sta_st_prev + out["ruas"][k - 1]["d"] - ts_prev
        delta, arah = sudut_belok(out["ruas"][k - 1]["az"], out["ruas"][k]["az"])
        pi = dict(nama=nama, idx=k, xy=(r["X"], r["Y"]), delta=delta, arah=arah, sta_pi=sta_pi,
                  az_in=out["ruas"][k - 1]["az"], R=r["R"], Vr=r["Vr"], lurus=False, pesan=[])
        if delta < 0.01 or r["R"] <= 0:
            pi.update(lurus=True, Ts=0.0, Ltot=0.0, sta_ts=sta_pi, sta_st=sta_pi, jenis="Lurus", h=None, P=None, hasil=None)
            if delta >= 0.01 and r["R"] <= 0:
                out["peringatan"].append(f"{nama}: radius R belum diisi, tikungan diabaikan.")
            out["tabel_sta"].append((f"{nama} (lurus)", sta_pi))
        else:
            P = dict(P0)
            P.update(Vr=r["Vr"], Rc=r["R"], delta=delta, Ls_rencana=r["Ls"])
            hasil = {"FC": hitung_fc(P, sta_pi), "SCS": hitung_scs(P, sta_pi), "SS": hitung_ss(P, sta_pi)}
            jenis = r["Jenis"] if r["Jenis"] in hasil else rekomendasi(P, hasil)
            h = hasil[jenis]
            v = h["v"]
            Ts = v["Tc"] if jenis == "FC" else v["Ts"]
            Ltot = v["Lc"] if jenis == "FC" else v["Ltot"]
            pi.update(P=P, hasil=hasil, h=h, jenis=jenis, Ts=Ts, Ltot=Ltot, sta_ts=sta_pi - Ts, sta_st=sta_pi - Ts + Ltot)
            for ps in h["pesan"]:
                out["peringatan"].append(f"{nama} ({jenis}): {ps}")
            if jenis == "SCS" and v["thc"] <= 0:
                out["peringatan"].append(f"{nama}: SCS tidak valid (θc ≤ 0) → ganti ke SS atau perbesar Δ/perkecil Ls.")
            for lab, s in h["sta"]:
                out["tabel_sta"].append((f"{nama} · {lab}", s))
        out["pi"].append(pi)
        ts_list[k] = pi["Ts"]
        sta_st_prev, ts_prev = pi["sta_st"], pi["Ts"]
    sta_b = sta_st_prev + out["ruas"][-1]["d"] - ts_prev
    out["tabel_sta"].append(("B (akhir trase)", sta_b))
    out["sta_akhir"] = sta_b
    out["panjang"] = sta_b - sta_awal
    for i, rs in enumerate(out["ruas"]):
        bebas = rs["d"] - ts_list[i] - ts_list[i + 1]
        rs["bebas"] = bebas
        if bebas < 0:
            out["peringatan"].append(
                f"Ruas {rs['dari']}–{rs['ke']}: tangen kedua tikungan tumpang tindih {-bebas:.2f} m "
                f"(perkecil R atau geser PI)."
            )
    return out


def kurva_global(pi):
    """Titik-titik lengkung (koordinat X,Y sebenarnya) untuk gambar trase."""
    g = bangun_geometri(pi["h"], ext=1.0)
    th = math.radians(pi["az_in"])
    arah_masuk = np.array([math.sin(th), math.cos(th)])
    normal = np.array([-arah_masuk[1], arah_masuk[0]]) if pi["arah"] == "Kiri" else np.array([arah_masuk[1], -arah_masuk[0]])
    ts = np.array(pi["xy"]) - pi["Ts"] * arah_masuk
    c = g["curva"]
    return ts + np.outer(c[:, 0], arah_masuk) + np.outer(c[:, 1], normal)


# =============================================================================
#  GAMBAR DXF
# =============================================================================
SHEET_W, SHEET_H = 420.0, 297.0  # A3 landscape (mm)
SKALA_LIST = [50, 100, 150, 200, 250, 300, 350, 400, 500, 600, 750, 800, 1000, 1200, 1500, 2000, 2500, 3000, 5000, 7500, 10000]


class Kertas:
    """Pembantu menggambar dalam satuan lembar (mm). Titik model (m) -> lembar via S()."""

    def __init__(self, msp, ox, k, bc, pusat):
        self.m, self.ox, self.k, self.bc, self.pusat = msp, ox, k, bc, pusat

    # -- transformasi
    def S(self, p):
        return (self.pusat[0] + self.k * (p[0] - self.bc[0]), self.pusat[1] + self.k * (p[1] - self.bc[1]))

    # -- primitif
    def garis(self, a, b, layer, **kw):
        at = {"layer": layer}
        at.update(kw)
        self.m.add_line((a[0], a[1]), (b[0], b[1]), dxfattribs=at)

    def poli(self, pts, layer, close=False, **kw):
        at = {"layer": layer}
        at.update(kw)
        self.m.add_lwpolyline([(float(x), float(y)) for x, y in pts], format="xy", close=close, dxfattribs=at)

    def teks(self, s, p, h=2.5, layer="TEKS", rot=0.0, align="MIDDLE_CENTER"):
        rot = (rot + 180) % 360 - 180
        if rot > 90:
            rot -= 180
        elif rot <= -90:
            rot += 180
        t = self.m.add_text(s, height=h, dxfattribs={"layer": layer, "style": "ARIAL", "rotation": rot})
        t.set_placement((p[0], p[1]), align=_align(align))

    def tick(self, p, ang_deg, layer="DIMENSI", L=2.2):
        a = (ang_deg + 45) * D2R
        dx, dy = L * math.cos(a), L * math.sin(a)
        self.garis((p[0] - dx, p[1] - dy), (p[0] + dx, p[1] + dy), layer, lineweight=35)

    # -- dimensi garis (manual, gaya AutoCAD)
    def dim(self, p1, p2, off, teks, h=2.5):
        a, b = np.array(self.S(p1)), np.array(self.S(p2))
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-6:
            return
        d /= L
        n = np.array([-d[1], d[0]])
        a2, b2 = a + n * off, b + n * off
        sgn = 1 if off >= 0 else -1
        self.garis(a, a2 + n * 1.5 * sgn, "DIMENSI")
        self.garis(b, b2 + n * 1.5 * sgn, "DIMENSI")
        self.garis(a2, b2, "DIMENSI")
        ang = math.degrees(math.atan2(d[1], d[0]))
        self.tick(a2, ang)
        self.tick(b2, ang)
        mid = (a2 + b2) / 2 + n * 2.2 * sgn
        self.teks(teks, mid, h, "DIMENSI", ang)

    def busur_sudut(self, pusat_model, a0, a1, r_mm, teks, h=2.5, jarak=4.0):
        c = self.S(pusat_model)
        self.m.add_arc(c, r_mm, a0 % 360, a1 % 360, dxfattribs={"layer": "DIMENSI"})
        am = (a0 + a1) / 2 * D2R
        if teks:
            self.teks(teks, (c[0] + (r_mm + jarak) * math.cos(am), c[1] + (r_mm + jarak) * math.sin(am)), h, "DIMENSI")
        for ang in (a0, a1):
            self.tick((c[0] + r_mm * math.cos(ang * D2R), c[1] + r_mm * math.sin(ang * D2R)), ang + 90)

    def titik(self, nama, p_model, dx=3.0, dy=3.0, align="BOTTOM_LEFT"):
        c = self.S(p_model)
        self.m.add_circle(c, 0.9, dxfattribs={"layer": "TITIK"})
        self.teks(nama, (c[0] + dx, c[1] + dy), 3.0, "TEKS", align=align)


def _buat_doc():
    doc = ezdxf.new("R2010", setup=True)
    try:
        doc.units = ezdxf.units.MM
    except Exception:
        pass
    doc.header["$LTSCALE"] = 10
    if "ARIAL" not in doc.styles:
        doc.styles.add("ARIAL", font="arial.ttf")
    spesifikasi = {
        "FRAME": (7, "Continuous"), "TABEL": (7, "Continuous"), "TEKS": (7, "Continuous"),
        "TANGEN": (7, "Continuous"), "LENGKUNG": (1, "Continuous"), "TEPI": (8, "Continuous"),
        "RADIUS": (6, "DASHED"), "DIMENSI": (30, "Continuous"), "TITIK": (7, "Continuous"),
        "SUMBU": (8, "CENTER"), "LUAR": (1, "Continuous"), "DALAM": (150, "Continuous"),
    }
    for nama, (warna, lt) in spesifikasi.items():
        doc.layers.add(nama, color=warna, linetype=lt)
    return doc


def _kotak(ks, x0, y0, x1, y1, layer="FRAME", **kw):
    ks.poli([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, close=True, **kw)


def _strip_bawah(ks, ox, judul, skala, label=None):
    """Strip tipis di bawah lembar: hanya nama tikungan dan skala (tanpa kop proyek)."""
    x0, x1 = ox + 10, ox + SHEET_W - 10
    _kotak(ks, x0, 10, x1, 24, lineweight=50)
    ks.garis((x1 - 60, 10), (x1 - 60, 24), "FRAME")
    ks.teks(judul.upper(), (x0 + 4, 17), 4.0, align="MIDDLE_LEFT")
    ks.teks(label or f"SKALA 1 : {skala}", (x1 - 30, 17), 3.5)


def _tabel(ks, x, y_top, judul, data, w=(46, 38, 16), rh=6.0):
    """Tabel kecil data. data = [(label, nilai_str, satuan)]."""
    tw = sum(w)
    n = len(data) + 1
    _kotak(ks, x, y_top - n * rh, x + tw, y_top, "TABEL", lineweight=35)
    ks.teks(judul, (x + tw / 2, y_top - rh / 2), 3.0, align="MIDDLE_CENTER")
    for i, (lab, val, sat) in enumerate(data, start=1):
        yy = y_top - i * rh
        ks.garis((x, yy), (x + tw, yy), "TABEL")
        ks.teks(lab, (x + 2, yy - rh / 2), 2.4, align="MIDDLE_LEFT")
        ks.teks(val, (x + w[0] + w[1] - 2, yy - rh / 2), 2.4, align="MIDDLE_RIGHT")
        ks.teks(sat, (x + w[0] + w[1] + 2, yy - rh / 2), 2.4, align="MIDDLE_LEFT")
    ks.garis((x + w[0], y_top - rh), (x + w[0], y_top - n * rh), "TABEL")
    ks.garis((x + w[0] + w[1], y_top - rh), (x + w[0] + w[1], y_top - n * rh), "TABEL")
    return y_top - n * rh


def _detail_fc(msp, ox, g, v, y_atas):
    """Kotak detail diperbesar untuk FC (sudut belok kecil -> lengkung terlalu pipih pada gambar utama)."""
    x0, x1, y0, y1 = ox + 300, ox + 400, 30.0, y_atas
    if y1 - y0 < 45:
        return
    Tc, d, R = v["Tc"], v["delta"], v["R"]
    PI, CT, dB = g["PI"], g["ST"], g["dirB"]
    e = 0.5 * Tc
    ujung = CT + e * dB
    xmin, xmax = -e, max(PI[0], ujung[0])
    ymin, ymax = 0.0, max(ujung[1], 0.0)
    bw, bh = xmax - xmin, ymax - ymin
    N2 = next((n for n in SKALA_LIST if bw * 1000 / n <= 80 and bh * 1000 / n <= (y1 - y0) - 45), SKALA_LIST[-1])
    k2 = 1000.0 / N2
    bc = ((xmin + xmax) / 2, (ymin + ymax) / 2)
    ks = Kertas(msp, ox, k2, bc, ((x0 + x1) / 2, y0 + 10 + (y1 - y0 - 10) / 2 - 4))
    S = ks.S
    _kotak(ks, x0, y0, x1, y1, "TABEL", lineweight=35)
    ks.garis((x0, y1 - 8), (x1, y1 - 8), "TABEL")
    ks.teks(f"DETAIL TC - PI - CT   SKALA 1 : {N2}", ((x0 + x1) / 2, y1 - 4), 2.8)
    ks.garis(S((-e, 0)), S(PI), "TANGEN", lineweight=35)
    ks.garis(S(PI), S(ujung), "TANGEN", lineweight=35)
    msp.add_arc(S(g["O"]), k2 * R, 270 % 360, (270 + d) % 360, dxfattribs={"layer": "LENGKUNG", "lineweight": 70})
    ks.titik("TC", g["TC"], -6.0, -4.0)
    ks.titik("PI", PI, 2.5, -5.0)
    ks.titik("CT", CT, 2.5, 2.5)
    ks.dim(g["TC"], PI, -9, f"Tc = {v['Tc']:.4f}")
    ks.dim(PI, CT, -9, f"Tc = {v['Tc']:.4f}")
    c = S((Tc * 0.5, 0))
    ks.teks(f"Lc = {v['Lc']:.4f}   Ec = {v['Ec']:.4f}", (c[0] + 18, c[1] + 12), 2.5, "DIMENSI")
    ks.teks(f"Δ = {d:g}°", (c[0] + 18, c[1] + 17), 2.5, "DIMENSI")
    ks.teks(f"Garis radius ke pusat O  (R = {R:.4f})", (c[0] + 18, c[1] + 22), 2.5, "DIMENSI")
    ks.garis(S(g["TC"]), (S(g["TC"])[0], S(g["TC"])[1] + 8), "RADIUS")
    ks.garis(S(CT), (S(CT)[0] - 8 * math.sin(d * D2R), S(CT)[1] + 8 * math.cos(d * D2R)), "RADIUS")


def gambar_tikungan(doc, item, ox):
    """Gambar satu lembar tikungan pada model space dengan offset x = ox."""
    msp = doc.modelspace()
    hasil, P, peleb = item["h"], item["P"], item["peleb"]
    tipe, v = hasil["tipe"], hasil["v"]
    R, d = v["R"], v["delta"]
    Ts = v["Tc"] if tipe == "FC" else v["Ts"]
    ext = max(0.25 * Ts, 0.10 * R, 22.0)
    g = bangun_geometri(hasil, ext)

    # ---- bounding box & skala
    pts = np.vstack([g["center"], g["O"], g["PI"]])
    kiri, kanan = tepi_jalan(g["center"], g["t"], P["Bn"], peleb["db"])
    pts = np.vstack([pts, kiri, kanan])
    mn, mx = pts.min(axis=0), pts.max(axis=0)
    bw, bh = mx[0] - mn[0], mx[1] - mn[1]
    GX0, GX1, GY0, GY1 = ox + 20, ox + 292, 30, 282
    mar = 24
    uw, uh = (GX1 - GX0) - 2 * mar, (GY1 - GY0) - 2 * mar
    N = next((s for s in SKALA_LIST if bw * 1000 / s <= uw and bh * 1000 / s <= uh), SKALA_LIST[-1])
    k = 1000.0 / N
    bc = ((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2)
    pusat = ((GX0 + GX1) / 2, (GY0 + GY1) / 2)
    ks = Kertas(msp, ox, k, bc, pusat)

    # ---- bingkai lembar
    _kotak(ks, ox + 0, 0, ox + SHEET_W, SHEET_H, "FRAME")
    _kotak(ks, ox + 10, 10, ox + SHEET_W - 10, SHEET_H - 10, "FRAME", lineweight=70)
    _strip_bawah(ks, ox, item["judul"], N)

    # ---- tepi jalan
    S = ks.S
    ks.poli([S(p) for p in kiri], "TEPI")
    ks.poli([S(p) for p in kanan], "TEPI")

    # ---- tangen (garis lurus) & sumbu
    TS = np.array([0.0, 0.0])
    ks.garis(S((-ext, 0)), S(g["PI"]), "TANGEN", lineweight=35)
    ks.garis(S(g["PI"]), S(g["ST"] + ext * g["dirB"]), "TANGEN", lineweight=35)

    # ---- lengkung (merah, tebal)
    if tipe == "FC":
        a0, a1 = g["arc_ang"]
        msp.add_arc(S(g["O"]), k * R, a0 % 360, a1 % 360, dxfattribs={"layer": "LENGKUNG", "lineweight": 70})
    else:
        ks.poli([S(p) for p in g["s1"]], "LENGKUNG", lineweight=70)
        ks.poli([S(p) for p in g["s2"]], "LENGKUNG", lineweight=70)
        if g["arc_ang"]:
            a0, a1 = g["arc_ang"]
            msp.add_arc(S(g["O"]), k * R, a0 % 360, a1 % 360, dxfattribs={"layer": "LENGKUNG", "lineweight": 70})

    # ---- jari-jari & garis bantu
    O = g["O"]
    if tipe == "FC":
        ujung = [g["TC"], g["CT"]]
    else:
        ujung = [g["SC"], g["CS"]]
        foot1 = np.array([v["K"], 0.0])
        ks.garis(S(O), S(foot1), "RADIUS")
        u = (g["O"] - g["PI"]) / np.linalg.norm(g["O"] - g["PI"])
        foot2 = _refleksi(foot1, g["PI"], u)
        ks.garis(S(O), S(foot2), "RADIUS")
    for p in ujung:
        ks.garis(S(O), S(p), "RADIUS")
    ks.garis(S(g["PI"]), S(O), "SUMBU")

    # ---- titik & label
    ks.titik("PI", g["PI"], 2.5, 2.5)
    ks.titik("O", O, 2.5, 2.5)
    if tipe == "FC":
        ks.titik("TC", g["TC"], -6.5, -3.5, "BOTTOM_LEFT")
        ks.titik("CT", g["CT"], 2.5, 2.5)
    else:
        ks.titik("TS", TS, -7.0, -3.5)
        ks.titik("ST", g["ST"], 2.5, 2.5)
        if v["thc"] > 1e-6:
            ks.titik("SC", g["SC"], 2.5, -5.5)
            ks.titik("CS", g["CS"], 2.5, 2.5)
        else:
            ks.titik("SS", g["SC"], 2.5, -5.5)

    # ---- dimensi
    fv = lambda x: f"{x:.4f}"
    if tipe == "FC":
        ks.dim(g["TC"], g["PI"], -9, f"Tc = {fv(v['Tc'])}")
        rm = (np.array(S(O)) + np.array(S(g["CT"]))) / 2
        ks.teks(f"R = {fv(R)}", (rm[0] + 8, rm[1]), 3.0, "DIMENSI")
        mid = O + R * np.array([math.cos((270 + d / 2) * D2R), math.sin((270 + d / 2) * D2R)])
        ks.garis(S(g["PI"]), S(mid), "DIMENSI")
        pm = (np.array(S(g["PI"])) + np.array(S(mid))) / 2
        ks.teks(f"Ec = {fv(v['Ec'])}", (pm[0] + 12, pm[1] - 3), 2.5, "DIMENSI")
        cm = np.array(S(O)) + k * R * np.array([math.cos((270 + d / 2) * D2R), math.sin((270 + d / 2) * D2R)])
        ks.teks(f"Lc = {fv(v['Lc'])}", (cm[0] + 14, cm[1] - 7), 2.5, "DIMENSI")
        r_ang = max(6.0, min(0.3 * k * R, 14))
        ks.busur_sudut(O, 270, 270 + d, r_ang, f"Δ = {d:g}°", 2.5, 4)
    else:
        ks.dim(TS, np.array([v["K"], 0.0]), -9, f"K = {fv(v['K'])}")
        ks.dim(TS, np.array([v["Xc"], 0.0]), -18, f"{'Xc' if v['thc'] > 1e-6 else 'Xs'} = {fv(v['Xc'])}")
        ks.dim(TS, g["PI"], -27, f"Ts = {fv(v['Ts'])}")
        ks.dim(TS, g["SC"], 9, f"Ls = {fv(v['Ls'])}")
        r_ang = max(8.0, min(0.30 * k * R, 22))
        th_s, th_c = v["ths"], v["thc"]
        ks.busur_sudut(O, 270, 270 + th_s, r_ang, "")
        if th_c > 1e-6:
            ks.busur_sudut(O, 270 + th_s, 270 + th_s + th_c, r_ang + 6, "")
            ks.busur_sudut(O, 270 + th_s + th_c, 270 + d, r_ang, "")
            daftar = [f"θs = {th_s:.2f}°", f"θc = {th_c:.2f}°", f"θs = {th_s:.2f}°"]
        else:
            ks.busur_sudut(O, 270 + th_s, 270 + d, r_ang, "")
            daftar = [f"θs = {th_s:.2f}°", f"θs = {th_s:.2f}°"]
        oc = S(O)
        for i, tx in enumerate(daftar):
            ks.teks(tx, (oc[0] - 3, oc[1] + 3 - 5 * i), 2.5, "DIMENSI", align="MIDDLE_RIGHT")
        # Es: PI -> titik tengah busur
        am = (270 + d / 2) * D2R
        mid = O + R * np.array([math.cos(am), math.sin(am)])
        ks.garis(S(g["PI"]), S(mid), "DIMENSI")
        pm = (np.array(S(g["PI"])) + np.array(S(mid))) / 2
        ks.teks(f"Es = {fv(v['Es'])}", (pm[0] + 12, pm[1] - 3), 2.5, "DIMENSI")
        rm = (np.array(S(O)) + np.array(S((v["K"], 0.0)))) / 2
        ks.teks(f"R = {fv(R)}", (rm[0] - 11, rm[1]), 2.5, "DIMENSI", rot=90)
    # sudut belok Δ pada PI
    rp = 11.0
    ks.busur_sudut(g["PI"], 0, d, rp, f"Δ = {d:g}°", 2.5, 4)

    # ---- tabel data (kanan atas)
    if tipe == "FC":
        data = [
            ("Kecepatan rencana Vr", f"{P['Vr']:g}", "km/jam"), ("Radius R", f"{R:.2f}", "m"),
            ("Sudut belok Δ", f"{d:.2f}", "°"), ("Arah belok", item.get("arah", "-"), ""), ("Lc", f"{v['Lc']:.4f}", "m"),
            ("Tc", f"{v['Tc']:.4f}", "m"), ("Ec", f"{v['Ec']:.4f}", "m"),
        ]
    else:
        data = [
            ("Kecepatan rencana Vr", f"{P['Vr']:g}", "km/jam"), ("Radius R", f"{R:.2f}", "m"),
            ("Sudut belok Δ", f"{d:.2f}", "°"), ("Arah belok", item.get("arah", "-"), ""), ("Ls", f"{v['Ls']:.4f}", "m"),
            ("θs", f"{v['ths']:.4f}", "°"), ("θc", f"{v['thc']:.4f}", "°"),
            ("Lc", f"{v['Lc']:.4f}", "m"), ("Xc / Xs", f"{v['Xc']:.4f}", "m"),
            ("Yc / Ys", f"{v['Yc']:.4f}", "m"), ("P", f"{v['P']:.4f}", "m"),
            ("K", f"{v['K']:.4f}", "m"), ("Es", f"{v['Es']:.4f}", "m"),
            ("Ts", f"{v['Ts']:.4f}", "m"), ("L total", f"{v['Ltot']:.4f}", "m"),
        ]
    y_bawah = _tabel(ks, ox + 300, 280, f"DATA TIKUNGAN {tipe}", data)
    data2 = [
        ("Lebar normal Bn", f"{P['Bn']:.2f}", "m"), ("Lebar di tikungan Bt", f"{peleb['Bt']:.4f}", "m"),
        ("Pelebaran Δb", f"{peleb['db']:.4f}", "m"), ("Per sisi Δb/2", f"{peleb['db'] / 2:.4f}", "m"),
    ]
    y_bawah = _tabel(ks, ox + 300, y_bawah - 6, "PELEBARAN PERKERASAN", data2)
    data3 = [(n_, fmt_sta(s_), "") for n_, s_ in hasil["sta"]]
    y_end = _tabel(ks, ox + 300, y_bawah - 6, "STASIONING", data3, w=(46, 38, 16))
    if tipe == "FC":
        _detail_fc(msp, ox, g, v, y_end - 6)



def nomor_tikungan_label(tipe):
    return {"FC": "FC (FULL CIRCLE)", "SCS": "S-C-S (SPIRAL-CIRCLE-SPIRAL)", "SS": "S-S (SPIRAL-SPIRAL)"}[tipe]


def gambar_superelevasi(doc, item, ox):
    """Lembar A3 diagram superelevasi: grafik tepi luar/dalam, patok STA, dimensi, tabel, potongan melintang A-D."""
    msp = doc.modelspace()
    sp, h, P = item["supe"], item["h"], item["P"]
    tipe = sp["tipe"]
    e, en = sp["e"] * 100, sp["en"] * 100
    xa, xb, L = sp["xa1"], sp["xb2"], sp["L"]
    ext = 0.35 * L
    span = (xb - xa) + 2 * ext
    GX0, GX1 = ox + 20, ox + 292
    N = next((s for s in SKALA_LIST if span * 1000 / s <= (GX1 - GX0) - 62), SKALA_LIST[-1])
    k = 1000.0 / N
    xc = (xa + xb) / 2
    cx = (GX0 + GX1) / 2 + 12
    kv = min(5.0, 34.0 / max(e, en, 1.0))
    ybase, y_dim = 214.0, 142.0

    def X(x):
        return cx + k * (x - xc)

    def Y(pct):
        return ybase + kv * pct

    ks = Kertas(msp, ox, k, (xc, 0.0), (cx, ybase))
    kd = Kertas(msp, ox, k, (xc, 0.0), (cx, y_dim))
    _kotak(ks, ox + 0, 0, ox + SHEET_W, SHEET_H, "FRAME")
    _kotak(ks, ox + 10, 10, ox + SHEET_W - 10, SHEET_H - 10, "FRAME", lineweight=70)
    _strip_bawah(ks, ox, item["judul"] + " - DIAGRAM SUPERELEVASI", N, label=f"SKALA H 1 : {N}")

    # garis level kemiringan
    x_l, x_r = X(xa - ext), X(xb + ext)
    niv = sorted({round(v_, 4) for v_ in (e, en, 0.0, -en, -e)}, reverse=True)
    for pct in niv:
        ks.garis((x_l, Y(pct)), (x_r, Y(pct)), "TANGEN" if pct == 0 else "SUMBU")
        ks.teks(f"{pct:+.2f}%" if pct else "0%", (x_l - 3, Y(pct)), 2.3, "TEKS", align="MIDDLE_RIGHT")

    # patok stasiun
    y_top = Y(e) + 7
    for nm, x, sta in sp["titik"]:
        ks.garis((X(x), y_top), (X(x), y_dim), "SUMBU")
        ks.teks(nm, (X(x), y_top + 3.5), 2.8, "TEKS", align="MIDDLE_CENTER")
        ks.teks(f"STA {fmt_sta(sta)}", (X(x) + 1.3, Y(-e) - 5), 2.2, "TEKS", rot=90, align="MIDDLE_RIGHT")

    # tepi luar dan tepi dalam
    v_ = sp["verts"]
    pts_o = [(x_l, Y(-en))] + [(X(x), Y(o)) for x, o, _ in v_] + [(x_r, Y(-en))]
    pts_i = [(x_l, Y(-en))] + [(X(x), Y(i)) for x, _, i in v_] + [(x_r, Y(-en))]
    ks.poli(pts_i, "DALAM", lineweight=70)
    ks.poli(pts_o, "LUAR", lineweight=70)

    # penanda potongan A-D pada tepi luar
    for kc in sp["kunci"]:
        px, py = X(kc["x"]), Y(kc["outer"])
        msp.add_circle((px, py), 1.3, dxfattribs={"layer": "TITIK"})
        ks.teks(kc["huruf"], (px, py + 5), 3.0, "TEKS", align="MIDDLE_CENTER")

    # dimensi panjang antar patok
    t = sp["titik"]
    for (n1, x1, _), (n2, x2, _) in zip(t[:-1], t[1:]):
        d = x2 - x1
        if d > 1e-6:
            kd.dim((x1, 0.0), (x2, 0.0), -9, f"{d:.2f}", h=2.2)

    # legenda
    lg_x, lg_y = GX0 + 2, 276.0
    for i, (lay, tx) in enumerate((("LUAR", "Tepi luar"), ("DALAM", "Tepi dalam"), ("TANGEN", "As jalan (0%)"))):
        yy = lg_y - 5 * i
        ks.garis((lg_x, yy), (lg_x + 10, yy), lay, lineweight=70)
        ks.teks(tx, (lg_x + 13, yy), 2.4, "TEKS", align="MIDDLE_LEFT")

    if tipe == "FC":
        ks.teks("R1 awal naik, R2 e penuh, R3 mulai turun, R4 normal kembali", (lg_x, lg_y - 17), 2.2, "TEKS", align="MIDDLE_LEFT")

    # tabel kanan
    ls_lab = "Ls' (fiktif)" if tipe == "FC" else "Ls"
    data = [
        ("Kecepatan rencana Vr", f"{P['Vr']:g}", "km/jam"), ("Radius R", f"{P['Rc']:.2f}", "m"),
        ("e maks", f"{P['emax'] * 100:.2f}", "%"), ("e rencana", f"{e:.2f}", "%"), ("e normal", f"{en:.2f}", "%"),
        ("Lebar jalur Bn", f"{P['Bn']:.2f}", "m"), (ls_lab, f"{L:.4f}", "m"),
        ("Tepi luar 0% pada", f"{sp['x0']:.4f}", "m"), ("Tepi luar +en pada", f"{sp['x1']:.4f}", "m"),
        ("Perubahan kemiringan", f"{sp['re_akt']:.4f}", "m/m/det"),
    ]
    if tipe == "FC":
        data.append(("Porsi Ls' di lurus", f"{sp['p_tan'] * 100:.0f}", "%"))
    yb = _tabel(ks, ox + 300, 280, "DATA SUPERELEVASI", data)
    _tabel(ks, ox + 300, yb - 6, "STASIONING", [(n, fmt_sta(s), "") for n, _, s in sp["titik"]])

    # potongan melintang A-D
    bmm = 27.0
    kvs = min(2.0, 22.0 / max(e, en, 1.0))
    for idx, kc in enumerate(sp["kunci"]):
        bx0 = ox + 20 + 68 * idx
        bx1 = bx0 + 68
        mid = bx0 + 34
        _kotak(ks, bx0, 36, bx1, 122, "TABEL", lineweight=35)
        ks.teks(f"POTONGAN {kc['huruf']} ({kc['ket']})", (mid, 116.5), 2.6, "TEKS", align="MIDDLE_CENTER")
        ks.teks(f"STA {fmt_sta(kc['sta'])}", (mid, 111), 2.4, "TEKS", align="MIDDLE_CENTER")
        yb0 = 78.0
        pl = (mid - bmm, yb0 + kvs * kc["inner"])
        pr = (mid + bmm, yb0 + kvs * kc["outer"])
        ks.garis((bx0 + 5, yb0), (bx1 - 5, yb0), "SUMBU")
        ks.poli([pl, (mid, yb0), pr], "TANGEN", lineweight=50)
        msp.add_circle(pl, 1.1, dxfattribs={"layer": "DALAM"})
        msp.add_circle(pr, 1.1, dxfattribs={"layer": "LUAR"})
        msp.add_circle((mid, yb0), 0.9, dxfattribs={"layer": "TITIK"})
        ks.teks(fp(kc['inner']), (pl[0], pl[1] + 4.5), 2.4, "DIMENSI", align="MIDDLE_CENTER")
        ks.teks(fp(kc['outer']), (pr[0], pr[1] + 4.5), 2.4, "DIMENSI", align="MIDDLE_CENTER")
        ks.teks("tepi dalam", (pl[0] + 3, 58), 2.2, "TEKS", align="MIDDLE_CENTER")
        ks.teks("tepi luar", (pr[0] - 3, 58), 2.2, "TEKS", align="MIDDLE_CENTER")
        ks.teks("as", (mid, yb0 - 5), 2.2, "TEKS", align="MIDDLE_CENTER")
    ks.teks("Kemiringan = beda tinggi tepi terhadap as, dibagi setengah lebar jalur. Gambar vertikal diperbesar.",
            (ox + 20, 29), 2.2, "TEKS", align="MIDDLE_LEFT")


def buat_dxf(items):
    """items: list dict(h=hasil_tikungan, P=param, peleb=hasil_pelebaran, judul=str, arah=str).
    Satu lembar A3 per item, disusun berjajar ke kanan."""
    doc = _buat_doc()
    kursor = 0
    for it in items:
        gambar_tikungan(doc, it, ox=kursor * (SHEET_W + 40))
        kursor += 1
        if it.get("supe"):
            gambar_superelevasi(doc, it, ox=kursor * (SHEET_W + 40))
            kursor += 1
    try:
        from ezdxf import zoom
        zoom.extents(doc.modelspace(), factor=1.05)
    except Exception:
        pass
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode("utf-8"), doc


# =============================================================================
#  EXCEL DENGAN RUMUS HIDUP (sel biru = input, sel hitam = rumus Excel)
# =============================================================================
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

_FN = "Arial"
_F_IN = Font(name=_FN, size=10, color="0000FF")
_F_HIT = Font(name=_FN, size=10, color="000000")
_F_TXT = Font(name=_FN, size=10)
_F_B = Font(name=_FN, size=10, bold=True)
_FILL_IN = PatternFill("solid", fgColor="FFF2CC")
_FILL_HDR = PatternFill("solid", fgColor="1F4E78")
_FILL_SEC = PatternFill("solid", fgColor="DDEBF7")
_TIPIS = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_TIPIS, right=_TIPIS, top=_TIPIS, bottom=_TIPIS)


class LembarRumus:
    """Lembar 5 kolom: Parameter | Simbol | Rumus (teks) | Nilai (RUMUS EXCEL) | Satuan."""

    def __init__(self, ws, judul, catatan):
        self.ws, self.ref = ws, {}
        ws.sheet_view.showGridLines = False
        for kol, w in zip("ABCDE", (46, 10, 50, 18, 16)):
            ws.column_dimensions[kol].width = w
        ws.cell(1, 1, judul).font = Font(name=_FN, size=14, bold=True, color="1F4E78")
        self.r = 2
        for c in catatan:
            ws.cell(self.r, 1, c).font = Font(name=_FN, size=9, italic=True, color="595959")
            self.r += 1
        self.r += 1

    def bagian(self, teks):
        for c in range(1, 6):
            cell = self.ws.cell(self.r, c)
            cell.fill = _FILL_SEC
            cell.border = _BORDER
        self.ws.cell(self.r, 1, teks).font = _F_B
        self.r += 1
        for i, h in enumerate(("Parameter", "Simbol", "Rumus", "Nilai", "Satuan"), start=1):
            cell = self.ws.cell(self.r, i, h)
            cell.font = Font(name=_FN, size=10, bold=True, color="FFFFFF")
            cell.fill = _FILL_HDR
            cell.alignment = Alignment(horizontal="center")
            cell.border = _BORDER
        self.r += 1

    def _baris(self, key, nama, simbol, rumus, nilai, satuan, fmt, is_input):
        r = self.r
        self.ref[key] = f"$D${r}"
        for c, val in enumerate((nama, simbol, rumus), start=1):
            cell = self.ws.cell(r, c, val)
            cell.font = _F_TXT
            cell.border = _BORDER
        d = self.ws.cell(r, 4, nilai)
        d.number_format = fmt
        d.border = _BORDER
        d.alignment = Alignment(horizontal="right")
        if is_input:
            d.font, d.fill = _F_IN, _FILL_IN
        else:
            d.font = _F_HIT
        e = self.ws.cell(r, 5, satuan.replace("{self}", f"D{r}") if satuan.startswith("=") else satuan)
        e.font, e.border = _F_TXT, _BORDER
        self.r += 1

    def input(self, key, nama, simbol, nilai, satuan, fmt="General", rumus="input"):
        self._baris(key, nama, simbol, rumus, nilai, satuan, fmt, True)

    def hitung(self, key, nama, simbol, rumus, formula, satuan, fmt="0.0000"):
        self._baris(key, nama, simbol, rumus, "=" + formula.format(**self.ref), satuan, fmt, False)

    def sta(self, key, nama, formula):
        """Baris stasioning: nilai meter + teks 'km+m' (rumus) di kolom satuan."""
        self._baris(key, nama, "STA", "", "=" + formula.format(**self.ref), "=INT({self}/1000)&\"+\"&TEXT(MOD({self},1000),\"000.00\")", "0.000", False)

    def kosong(self):
        self.r += 1


def _sheet_parameter(ws, P, sta_pi, jenis):
    L = LembarRumus(ws, "PERHITUNGAN TIKUNGAN : FC · SCS · SS", [
        "Sel BIRU berlatar kuning = input (boleh diubah). Sel HITAM = rumus Excel, otomatis menghitung ulang.",
        f"Jenis tikungan yang dipilih pada aplikasi: {jenis}.  Rujukan: Bina Marga (TPGJAK 1997 / Pedoman Desain Geometrik Jalan).",
    ])
    L.bagian("A. DATA INPUT")
    L.input("Vr", "Kecepatan rencana", "Vr", P["Vr"], "km/jam")
    L.input("R", "Radius tikungan rencana", "Rc", P["Rc"], "m")
    L.input("D", "Sudut belok", "Δ", P["delta"], "°", "0.0000")
    L.input("emax", "Superelevasi maksimum", "e maks", P["emax"], "-", "0.0%")
    L.input("en", "Superelevasi normal", "en", P["en"], "-", "0.0%")
    L.input("Cc", "Perubahan percepatan", "C", P["Cc"], "m/det³", "0.00")
    L.input("C1", "Konstanta kriteria 1 (Shortt)", "C₁", P["C1"], "-", "0.00")
    L.input("T", "Waktu tempuh pada lengkung peralihan", "T", P["T"], "detik", "0.0")
    L.input("re_in", "Landai relatif (0 = otomatis)", "re", P["re"], "-", "0.000")
    L.input("Ls_in", "Ls rencana SCS (0 = otomatis)", "Ls", P["Ls_rencana"], "m", "0.00")
    L.input("sta", "Stasioning PI", "STA PI", sta_pi, "m", "0.000")
    L.kosong()

    L.bagian("B. PARAMETER DASAR")
    L.hitung("re", "Landai relatif yang dipakai", "re", "0,025 (Vr≤70) / 0,035", "IF({re_in}>0,{re_in},IF({Vr}<=70,0.025,0.035))", "-", "0.000")
    L.hitung("f", "Koefisien gesek melintang maksimum", "f", "−0,00065·Vr+0,192 (Vr<80); −0,00125·Vr+0,24", "IF({Vr}<80,-0.00065*{Vr}+0.192,-0.00125*{Vr}+0.24)", "-")
    L.hitung("Rmin", "Radius minimum", "Rmin", "Vr² / [127(e maks + f)]", "{Vr}^2/(127*({emax}+{f}))", "m", "0.00")
    L.hitung("cekR", "Cek radius rencana", "Rc ≥ Rmin", "", "IF({R}>={Rmin},\"OK\",\"TIDAK OK\")", "-", "General")
    L.kosong()

    L.bagian("C. TIKUNGAN FULL CIRCLE (FC)")
    L.hitung("fc_Lc", "Panjang busur lingkaran", "Lc", "Δ·π·R / 180", "{D}*PI()*{R}/180", "m")
    L.hitung("fc_Tc", "Jarak TC ke PI", "Tc", "R·tan(Δ/2)", "{R}*TAN(RADIANS({D}/2))", "m")
    L.hitung("fc_Ec", "Jarak PI ke busur", "Ec", "Tc·tan(Δ/4)", "{fc_Tc}*TAN(RADIANS({D}/4))", "m")
    L.sta("fc_s1", "STA TC", "{sta}-{fc_Tc}")
    L.sta("fc_s2", "STA CT", "{fc_s1}+{fc_Lc}")
    L.kosong()

    L.bagian("D. TIKUNGAN SPIRAL-CIRCLE-SPIRAL (SCS)")
    L.hitung("k1", "Ls min kriteria 1 (Shortt)", "Ls₁", "0,0214·Vr³ / (R·C₁)", "0.0214*{Vr}^3/({R}*{C1})", "m")
    L.hitung("k2", "Ls min kriteria 2 (waktu tempuh)", "Ls₂", "Vr/3,6 · T", "{Vr}/3.6*{T}", "m")
    L.hitung("k3", "Ls min kriteria 3 (gaya sentrifugal)", "Ls₃", "0,022·Vr³/(R·C) − 2,727·Vr·e/C", "0.022*{Vr}^3/({R}*{Cc})-2.727*{Vr}*{emax}/{Cc}", "m")
    L.hitung("k4", "Ls min kriteria 4 (landai relatif)", "Ls₄", "(e maks − en)·Vr / (3,6·re)", "({emax}-{en})*{Vr}/(3.6*{re})", "m")
    L.hitung("lsmin", "Ls minimum (terbesar)", "Ls min", "MAX(Ls₁ … Ls₄)", "MAX({k1},{k2},{k3},{k4})", "m")
    L.hitung("s_Ls", "Ls rencana", "Ls", "input, atau dibulatkan ke atas kelipatan 5", "IF({Ls_in}>0,{Ls_in},CEILING({lsmin},5))", "m")
    L.hitung("s_ths", "Sudut spiral", "θs", "90·Ls / (π·R)", "90*{s_Ls}/(PI()*{R})", "°")
    L.hitung("s_thc", "Sudut busur lingkaran", "θc", "Δ − 2θs", "{D}-2*{s_ths}", "°")
    L.hitung("s_Lc", "Panjang busur lingkaran", "Lc", "θc·π·R / 180", "IF({s_thc}>0,{s_thc}*PI()*{R}/180,0)", "m")
    L.hitung("s_Lt", "Panjang total tikungan", "Ltot", "Lc + 2Ls", "{s_Lc}+2*{s_Ls}", "m")
    L.hitung("s_Xc", "Absis SC", "Xc", "Ls − Ls³/(40R²)", "{s_Ls}-{s_Ls}^3/(40*{R}^2)", "m")
    L.hitung("s_Yc", "Ordinat SC", "Yc", "Ls²/(6R)", "{s_Ls}^2/(6*{R})", "m")
    L.hitung("s_P", "Pergeseran busur", "P", "Yc − R(1 − cos θs)", "{s_Yc}-{R}*(1-COS(RADIANS({s_ths})))", "m")
    L.hitung("s_K", "Absis pusat busur", "K", "Xc − R·sin θs", "{s_Xc}-{R}*SIN(RADIANS({s_ths}))", "m")
    L.hitung("s_Es", "Jarak luar PI ke busur", "Es", "(R+P)/cos(Δ/2) − R", "({R}+{s_P})/COS(RADIANS({D}/2))-{R}", "m")
    L.hitung("s_Ts", "Jarak TS ke PI", "Ts", "(R+P)·tan(Δ/2) + K", "({R}+{s_P})*TAN(RADIANS({D}/2))+{s_K}", "m")
    L.hitung("s_c1", "Cek Ls ≥ Ls min", "", "", "IF({s_Ls}>={lsmin},\"OK\",\"Ls < Ls min\")", "-", "General")
    L.hitung("s_c2", "Cek bentuk SCS", "", "θc > 0 dan Lc ≥ 20 m", "IF({s_thc}>0,IF({s_Lc}>=20,\"OK\",\"Lc < 20 m, pakai SS\"),\"θc ≤ 0, pakai SS\")", "-", "General")
    L.sta("s_s1", "STA TS", "{sta}-{s_Ts}")
    L.sta("s_s2", "STA SC", "{s_s1}+{s_Ls}")
    L.sta("s_s3", "STA CS", "{s_s2}+{s_Lc}")
    L.sta("s_s4", "STA ST", "{s_s3}+{s_Ls}")
    L.kosong()

    L.bagian("E. TIKUNGAN SPIRAL-SPIRAL (SS)")
    L.hitung("ss_ths", "Sudut spiral", "θs", "Δ / 2", "{D}/2", "°")
    L.hitung("ss_Ls", "Panjang spiral", "Ls", "θs·π·R / 90", "{ss_ths}*PI()*{R}/90", "m")
    L.hitung("ss_c", "Cek Ls ≥ Ls min", "", "Ls min dari bagian D", "IF({ss_Ls}>={lsmin},\"OK\",\"Ls < Ls min\")", "-", "General")
    L.hitung("ss_Xs", "Absis SS", "Xs", "Ls − Ls³/(40R²)", "{ss_Ls}-{ss_Ls}^3/(40*{R}^2)", "m")
    L.hitung("ss_Ys", "Ordinat SS", "Ys", "Ls²/(6R)", "{ss_Ls}^2/(6*{R})", "m")
    L.hitung("ss_P", "Pergeseran busur", "P", "Ys − R(1 − cos θs)", "{ss_Ys}-{R}*(1-COS(RADIANS({ss_ths})))", "m")
    L.hitung("ss_K", "Absis pusat busur", "K", "Xs − R·sin θs", "{ss_Xs}-{R}*SIN(RADIANS({ss_ths}))", "m")
    L.hitung("ss_Es", "Jarak luar PI ke busur", "Es", "(R+P)/cos(Δ/2) − R", "({R}+{ss_P})/COS(RADIANS({D}/2))-{R}", "m")
    L.hitung("ss_Ts", "Jarak TS ke PI", "Ts", "(R+P)·tan(Δ/2) + K", "({R}+{ss_P})*TAN(RADIANS({D}/2))+{ss_K}", "m")
    L.hitung("ss_Lt", "Panjang total tikungan", "Ltot", "2·Ls", "2*{ss_Ls}", "m")
    L.sta("ss_s1", "STA TS", "{sta}-{ss_Ts}")
    L.sta("ss_s2", "STA SS", "{ss_s1}+{ss_Ls}")
    L.sta("ss_s3", "STA ST", "{ss_s2}+{ss_Ls}")
    ws.freeze_panes = "A4"


def _sheet_pelebaran(ws, P):
    L = LembarRumus(ws, "PELEBARAN PERKERASAN DI TIKUNGAN", [
        "Sel BIRU berlatar kuning = input. Sel HITAM = rumus Excel.",
        "Rumus mengikuti Bina Marga (kendaraan rencana: p, A, b). Td memakai (n+1) bila flag = 1 (sesuai laporan), (n−1) bila 0.",
    ])
    L.bagian("A. DATA INPUT")
    L.input("Vr", "Kecepatan rencana", "Vr", P["Vr"], "km/jam")
    L.input("R", "Radius tikungan", "R", P["Rc"], "m")
    L.input("p", "Jarak gandar kendaraan rencana", "p", P["p"], "m", "0.00")
    L.input("A", "Tonjolan depan kendaraan", "A", P["A"], "m", "0.00")
    L.input("b", "Lebar kendaraan rencana", "b", P["b"], "m", "0.00")
    L.input("n", "Jumlah lajur", "n", P["n"], "lajur", "0")
    L.input("Bn", "Lebar perkerasan pada bagian lurus", "Bn", P["Bn"], "m", "0.00")
    L.input("kz", "Koefisien Z", "kz", P["kz"], "-", "0.000")
    L.input("flag", "Flag Td: 1 = (n+1), 0 = (n−1)", "flag", 1 if P["td_n_plus_1"] else 0, "-", "0")
    L.kosong()
    L.bagian("B. HASIL")
    L.hitung("C", "Clearance samping", "C", "Bn/2 − b", "{Bn}/2-{b}", "m")
    L.hitung("b2", "Off-tracking kendaraan", "b''", "R − √(R² − p²)", "{R}-SQRT({R}^2-{p}^2)", "m")
    L.hitung("bp", "Lebar kendaraan di tikungan", "b'", "b + b''", "{b}+{b2}", "m")
    L.hitung("Td", "Tonjolan depan kendaraan", "Td", "√(R² + A(2p + A)) − R", "SQRT({R}^2+{A}*(2*{p}+{A}))-{R}", "m")
    L.hitung("Z", "Faktor kesulitan mengemudi", "Z", "kz·Vr / √R", "{kz}*{Vr}/SQRT({R})", "m")
    L.hitung("ktd", "Pengali Td", "n±1", "n+1 atau n−1", "IF({flag}=1,{n}+1,{n}-1)", "-", "0")
    L.hitung("Bt", "Lebar perkerasan di tikungan", "Bt", "n(b'+C) + (n±1)·Td + Z", "{n}*({bp}+{C})+{ktd}*{Td}+{Z}", "m")
    L.hitung("db", "Kebutuhan pelebaran total", "Δb", "Bt − Bn", "{Bt}-{Bn}", "m")
    L.hitung("db2", "Pelebaran per sisi", "Δb/2", "Δb / 2", "{db}/2", "m")
    L.hitung("perlu", "Perlu pelebaran?", "", "Δb > 0", "IF({db}>0,\"Ya\",\"Tidak\")", "-", "General")


def _sheet_jarak_pandang(ws, P, jp):
    L = LembarRumus(ws, "JARAK PANDANG HENTI (JPH) & MENDAHULUI (JPM)", [
        "Sel BIRU berlatar kuning = input. Sel HITAM = rumus Excel.",
        "Kelandaian G: positif = tanjakan, negatif = turunan.",
    ])
    L.bagian("A. DATA INPUT")
    L.input("Vr", "Kecepatan rencana", "Vr", P["Vr"], "km/jam")
    L.input("t", "Waktu reaksi", "t", jp["t_r"], "detik", "0.0")
    L.input("a", "Perlambatan", "a", jp["a_dec"], "m/det²", "0.00")
    L.input("G", "Kelandaian memanjang", "G", jp["G"], "-", "0.0%")
    L.input("m", "Selisih kecepatan kendaraan", "m", jp["m_sel"], "km/jam", "0")
    L.input("d3", "Jarak bebas kendaraan", "d₃", jp["d3"], "m", "0")
    L.input("jph_std", "JPH minimum standar (tabel Bina Marga)", "JPH std", jp["jph_std"], "m", "0")
    L.input("jpm_std", "JPM minimum standar (TPGJAK 038/TBM/1997)", "JPM std", jp["jpm_std"], "m", "0")
    L.kosong()
    L.bagian("B. JARAK PANDANG HENTI (JPH)")
    L.hitung("h1", "Jarak reaksi", "d₁", "Vr·t / 3,6", "{Vr}*{t}/3.6", "m")
    L.hitung("h2", "Jarak pengereman", "d₂", "Vr² / [2·3,6²·9,81·(a/9,81 + G)]", "{Vr}^2/(2*3.6^2*9.81*({a}/9.81+{G}))", "m")
    L.hitung("JPH", "Jarak pandang henti", "JPH", "d₁ + d₂", "{h1}+{h2}", "m")
    L.hitung("hc", "Cek terhadap standar", "", "JPH ≥ JPH std", "IF({JPH}>={jph_std},\"OK\",\"Di bawah standar\")", "-", "General")
    L.kosong()
    L.bagian("C. JARAK PANDANG MENDAHULUI (JPM)")
    L.hitung("T1", "Waktu penyesuaian awal", "T₁", "2,12 + 0,026·Vr", "2.12+0.026*{Vr}", "detik", "0.000")
    L.hitung("T2", "Waktu di lajur lawan", "T₂", "6,56 + 0,048·Vr", "6.56+0.048*{Vr}", "detik", "0.000")
    L.hitung("ja", "Percepatan rata-rata", "a", "2,052 + 0,0036·Vr", "2.052+0.0036*{Vr}", "km/jam/det", "0.000")
    L.hitung("j1", "Jarak selama waktu tanggap", "d₁", "0,278·T₁·(Vr − m + a·T₁/2)", "0.278*{T1}*({Vr}-{m}+{ja}*{T1}/2)", "m")
    L.hitung("j2", "Jarak selama mendahului", "d₂", "0,278·Vr·T₂", "0.278*{Vr}*{T2}", "m")
    L.hitung("j4", "Jarak kendaraan lawan", "d₄", "2/3 · d₂", "2/3*{j2}", "m")
    L.hitung("JPM", "Jarak pandang mendahului", "JPM", "d₁ + d₂ + d₃ + d₄", "{j1}+{j2}+{d3}+{j4}", "m")
    L.hitung("jc", "Cek terhadap standar", "", "JPM ≥ JPM std", "IF({JPM}>={jpm_std},\"OK\",\"Di bawah standar\")", "-", "General")


def _sheet_trase(ws, rows, sta_awal, P):
    ws.sheet_view.showGridLines = False
    ws.cell(1, 1, "JARAK, AZIMUT, SUDUT BELOK & STASIONING TRASE").font = Font(name=_FN, size=14, bold=True, color="1F4E78")
    ws.cell(2, 1, "Sel BIRU berlatar kuning = input (koordinat X=Easting, Y=Northing; R, Vr, jenis, Ls). Sel HITAM = rumus. "
                  "Jenis 'Otomatis' pada aplikasi sudah diterjemahkan menjadi FC/SCS/SS.").font = Font(name=_FN, size=9, italic=True, color="595959")
    ws.cell(3, 1, "STA PI(k) = STA ST(k−1) + d(k−1,k) − Ts(k−1)").font = Font(name=_FN, size=9, italic=True, color="595959")
    glob = [("STA awal (m)", sta_awal, "0.000"), ("e maks", P["emax"], "0.0%"), ("e normal", P["en"], "0.0%"),
            ("C (m/det³)", P["Cc"], "0.00"), ("C₁ kriteria 1", P["C1"], "0.00"), ("T (detik)", P["T"], "0.0"), ("re (0 = otomatis)", P["re"], "0.000")]
    for i, (lab, val, fmt) in enumerate(glob):
        ws.cell(5 + i, 1, lab).font = _F_TXT
        c = ws.cell(5 + i, 2, val)
        c.font, c.fill, c.number_format, c.border = _F_IN, _FILL_IN, fmt, _BORDER
    STA0, EM, EN, CC, C1, TT, REIN = ("$B$5", "$B$6", "$B$7", "$B$8", "$B$9", "$B$10", "$B$11")
    hdr = ["Titik", "X (m)", "Y (m)", "R (m)", "Vr (km/jam)", "Jenis", "Ls rencana (m)", "Jarak ke titik berikut (m)", "Azimut ruas (°)",
           "Δ (°)", "Arah", "Ls min (m)", "Ls (m)", "θs (°)", "θc (°)", "Lc (m)", "Xc (m)", "Yc (m)", "P (m)", "K (m)", "Ts (m)",
           "Es (m)", "Ltot (m)", "STA TS (m)", "STA PI (m)", "STA ST (m)", "Cek ruas", "STA TS", "STA PI", "STA ST"]
    h0 = 13
    for i, h in enumerate(hdr, start=1):
        c = ws.cell(h0, i, h)
        c.font = Font(name=_FN, size=10, bold=True, color="FFFFFF")
        c.fill = _FILL_HDR
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = _BORDER
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.row_dimensions[h0].height = 32
    n = len(rows)
    for i, rw in enumerate(rows):
        r = h0 + 1 + i
        nama = nama_titik(i, n)
        ws.cell(r, 1, nama).font = _F_B

        def put(col, val, fmt="0.0000", inp=False):
            c = ws.cell(r, col, val)
            c.number_format = fmt
            c.border = _BORDER
            c.font = _F_IN if inp else _F_HIT
            if inp:
                c.fill = _FILL_IN
            return c

        put(2, rw["X"], "0.000", True)
        put(3, rw["Y"], "0.000", True)
        if i < n - 1:
            put(8, f"=SQRT((B{r+1}-B{r})^2+(C{r+1}-C{r})^2)", "0.000")
            put(9, f"=MOD(DEGREES(ATAN2(C{r+1}-C{r},B{r+1}-B{r})),360)", "0.0000")
            put(27, f"=IF(H{r}-U{r}-U{r+1}>=0,\"OK\",\"TUMPANG TINDIH\")", "General")
        if i == 0:
            for col in (21, 23):
                put(col, 0, "0.0000")
            put(24, f"={STA0}", "0.000")
            put(25, f"={STA0}", "0.000")
            put(26, f"={STA0}", "0.000")
        elif i == n - 1:
            put(21, 0, "0.0000")
            put(23, 0, "0.0000")
            put(25, f"=Z{r-1}+H{r-1}-U{r-1}", "0.000")
            put(24, f"=Y{r}", "0.000")
            put(26, f"=Y{r}", "0.000")
        else:
            put(4, rw["R"] if rw["R"] > 0 else 1000.0, "0.00", True)
            put(5, rw["Vr"], "0", True)
            put(6, rw.get("jenis_excel", "FC"), "General", True)
            put(7, rw["Ls"], "0.00", True)
            put(10, f"=ABS(MOD(I{r}-I{r-1}+180,360)-180)", "0.0000")
            put(11, f"=IF(MOD(I{r}-I{r-1}+180,360)-180>0,\"Kanan\",\"Kiri\")", "General")
            put(12, f"=MAX(0.0214*E{r}^3/(D{r}*{C1}),E{r}/3.6*{TT},0.022*E{r}^3/(D{r}*{CC})-2.727*E{r}*{EM}/{CC},"
                    f"({EM}-{EN})*E{r}/(3.6*IF({REIN}>0,{REIN},IF(E{r}<=70,0.025,0.035))))")
            put(13, f"=IF(F{r}=\"FC\",0,IF(F{r}=\"SS\",J{r}/2*PI()*D{r}/90,IF(G{r}>0,G{r},CEILING(L{r},5))))")
            put(14, f"=IF(M{r}=0,0,90*M{r}/(PI()*D{r}))")
            put(15, f"=J{r}-2*N{r}")
            put(16, f"=MAX(O{r},0)*PI()*D{r}/180")
            put(17, f"=M{r}-M{r}^3/(40*D{r}^2)")
            put(18, f"=M{r}^2/(6*D{r})")
            put(19, f"=R{r}-D{r}*(1-COS(RADIANS(N{r})))")
            put(20, f"=Q{r}-D{r}*SIN(RADIANS(N{r}))")
            put(21, f"=(D{r}+S{r})*TAN(RADIANS(J{r}/2))+T{r}")
            put(22, f"=(D{r}+S{r})/COS(RADIANS(J{r}/2))-D{r}")
            put(23, f"=P{r}+2*M{r}")
            put(25, f"=Z{r-1}+H{r-1}-U{r-1}", "0.000")
            put(24, f"=Y{r}-U{r}", "0.000")
            put(26, f"=X{r}+W{r}", "0.000")
        for col_src, col_dst in ((24, 28), (25, 29), (26, 30)):
            L_ = get_column_letter(col_src)
            put(col_dst, f"=INT({L_}{r}/1000)&\"+\"&TEXT(MOD({L_}{r},1000),\"000.00\")", "General")
    r_end = h0 + n
    ws.cell(r_end + 2, 1, "Panjang total trase (m)").font = _F_B
    c = ws.cell(r_end + 2, 4, f"=Y{r_end}-{STA0}")
    c.font, c.number_format = _F_HIT, "0.000"
    ws.freeze_panes = ws.cell(h0 + 1, 2)


def _sheet_superelevasi(ws, P, sup):
    L = LembarRumus(ws, "DIAGRAM SUPERELEVASI", [
        "Sel BIRU berlatar kuning = input. Sel HITAM = rumus Excel.",
        "Putaran terhadap as jalan. Kemiringan = beda tinggi tepi terhadap as dibagi setengah lebar jalur (+ naik).",
        "Tepi luar naik linier dari -en ke +e. Tepi dalam tetap -en sampai tepi luar mencapai +en, lalu turun ke -e.",
    ])
    L.bagian("A. DATA INPUT")
    L.input("tipe", "Jenis tikungan (FC / SCS / SS)", "", sup["tipe"], "-", "General")
    L.input("Vr", "Kecepatan rencana", "Vr", P["Vr"], "km/jam")
    L.input("R", "Radius tikungan", "Rc", P["Rc"], "m")
    L.input("emax", "Superelevasi maksimum", "e maks", P["emax"], "-", "0.0%")
    L.input("en", "Superelevasi normal", "en", P["en"], "-", "0.0%")
    L.input("re_in", "Landai relatif (0 = otomatis)", "re", P["re"], "-", "0.000")
    L.input("e_in", "Superelevasi manual (0 = otomatis)", "e", sup["e_manual"], "-", "0.00%")
    L.input("Ls_in", "Ls (SCS, SS) atau Ls' fiktif (FC) yang dipakai", "L", sup["L"], "m", "0.0000")
    L.input("Lc", "Panjang busur lingkaran", "Lc", sup["Lc"], "m", "0.0000")
    L.input("p", "Porsi Ls' pada bagian lurus (khusus FC)", "p", sup["p_tan"], "-", "0.00")
    L.input("sta0", "STA TS (SCS, SS) atau TC (FC)", "STA", sup["sta0"], "m", "0.000")
    L.kosong()
    L.bagian("B. SUPERELEVASI RENCANA")
    L.hitung("f", "Koefisien gesek maksimum", "f", "−0,00065·Vr+0,192 (Vr<80); −0,00125·Vr+0,24", "IF({Vr}<80,-0.00065*{Vr}+0.192,-0.00125*{Vr}+0.24)", "-")
    L.hitung("Dmax", "Derajat kelengkungan maksimum", "Dmax", "181913,53·(e maks+f)/Vr²", "181913.53*({emax}+{f})/{Vr}^2", "°")
    L.hitung("D", "Derajat kelengkungan rencana", "D", "1432,4 / R", "1432.4/{R}", "°")
    L.hitung("e_auto", "e menurut rumus Bina Marga", "e", "−emax·D²/Dmax² + 2·emax·D/Dmax", "IF({D}>={Dmax},{emax},-{emax}*{D}^2/{Dmax}^2+2*{emax}*{D}/{Dmax})", "-", "0.00%")
    L.hitung("e", "e rencana yang dipakai", "e", "MAX(e manual atau e rumus, en)", "MAX(IF({e_in}>0,{e_in},{e_auto}),{en})", "-", "0.00%")
    L.hitung("re", "Landai relatif maksimum", "re maks", "0,025 (Vr≤70) / 0,035", "IF({re_in}>0,{re_in},IF({Vr}<=70,0.025,0.035))", "m/m/det", "0.000")
    L.kosong()
    L.bagian("C. PENCAPAIAN SUPERELEVASI")
    L.hitung("u0", "Fraksi pencapaian: tepi luar 0%", "u₀", "en / (e + en)", "{en}/({e}+{en})", "-")
    L.hitung("u1", "Fraksi pencapaian: tepi luar +en", "u₁", "2·en / (e + en)", "MIN(2*{en}/({e}+{en}),1)", "-")
    L.hitung("x0", "Jarak tepi luar 0% dari awal pencapaian", "x₀", "u₀·L", "{u0}*{Ls_in}", "m")
    L.hitung("x1", "Jarak tepi luar +en dari awal pencapaian", "x₁", "u₁·L", "{u1}*{Ls_in}", "m")
    L.hitung("rea", "Tingkat perubahan kemiringan aktual", "re", "(e + en)·Vr / (3,6·L)", "({e}+{en})*{Vr}/(3.6*{Ls_in})", "m/m/det")
    L.hitung("cek", "Cek terhadap landai relatif maksimum", "", "re aktual ≤ re maks", "IF({rea}<={re}+0.000000001,\"OK\",\"Perbesar Ls\")", "-", "General")
    L.hitung("Lfc", "Ls' fiktif FC otomatis (referensi)", "Ls'", "(e + en)·Vr / (3,6·re)", "({e}+{en})*{Vr}/(3.6*{re})", "m")
    L.hitung("xa", "Awal pencapaian terhadap TS/TC", "xa", "FC: −p·Ls'; SCS dan SS: 0", "IF({tipe}=\"FC\",-{p}*{Ls_in},0)", "m")
    L.hitung("xb", "Akhir pencapaian terhadap TS/TC", "xb", "FC: Lc+p·Ls'; SCS: 2Ls+Lc; SS: 2Ls", "IF({tipe}=\"FC\",{Lc}+{p}*{Ls_in},IF({tipe}=\"SCS\",2*{Ls_in}+{Lc},2*{Ls_in}))", "m")
    L.kosong()
    L.bagian("D. KEMIRINGAN TEPI PADA POTONGAN A - D")
    for huruf, fo, fi, fx in (
        ("A", "-{en}", "-{en}", "{xa}"),
        ("B", "0", "-{en}", "{xa}+{x0}"),
        ("C", "{en}", "-{en}", "{xa}+{x1}"),
        ("D", "{e}", "-{e}", "{xa}+{Ls_in}"),
    ):
        L.hitung(f"o{huruf}", f"Potongan {huruf}: tepi luar", "", "", fo, "-", "0.00%")
        L.hitung(f"i{huruf}", f"Potongan {huruf}: tepi dalam", "", "", fi, "-", "0.00%")
        L.sta(f"s{huruf}", f"Potongan {huruf}: STA", "{sta0}+" + fx)
    ws.freeze_panes = "A4"


def buat_excel(P, sta_pi, jenis, jp, trase_rows, sta_awal, sup=None):
    """P : parameter tikungan aktif. trase_rows : baris trase (dengan kunci 'jenis_excel')."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Parameter"
    _sheet_parameter(ws, P, sta_pi, jenis)
    if sup:
        _sheet_superelevasi(wb.create_sheet("Superelevasi"), P, sup)
    _sheet_pelebaran(wb.create_sheet("Pelebaran"), P)
    _sheet_jarak_pandang(wb.create_sheet("Jarak Pandang"), P, jp)
    _sheet_trase(wb.create_sheet("Trase & STA"), trase_rows, sta_awal, P)
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ===== UI =====================================================================
APP_NAMA = "GeoJalan"
APP_VERSI = "1.0"
PEMBUAT = ""  # isi nama tim/pembuat bila ingin ditampilkan di halaman Tentang

PAGES = ["Beranda", "Materi", "Trase & STA", "Tikungan", "Pelebaran", "Jarak Pandang", "Gambar & Excel", "Tentang"]

DEF = dict(
    Vr=80.0, Rc=240.0, delta=16.8, emax=8.0, sta_pi=385.0, jenis="Otomatis (rekomendasi)", sumber="Input manual",
    pi_pilih="PI-1", en=2.0, Cc=0.4, C1=1.0, T=3.0, re=0.0, Ls_rencana=0.0,
    p=7.6, A=2.1, b=2.6, n=2, Bn=7.0, kz=0.1, tdn=True,
    t_r=2.5, a_dec=3.4, G=0.0, m_sel=15.0, d3=100.0,
    sta_awal=0.0, semua=False, e_mode="Otomatis (rumus Bina Marga)", e_manual=6.0, p_tan=0.75, Ls_fc=0.0, supe_dxf=True, mode_out="Tikungan aktif (menu Tikungan)",
)

TRASE_DEFAULT = pd.DataFrame({
    "X": [0.0, 300.0, 500.0, 850.0, 1100.0],
    "Y": [0.0, 100.0, 350.0, 420.0, 380.0],
    "R": [np.nan, 150.0, 200.0, 300.0, np.nan],
    "Vr": [np.nan, 60.0, 60.0, 60.0, np.nan],
    "Jenis": [None, "Otomatis", "Otomatis", "Otomatis", None],
    "Ls": [np.nan, 0.0, 0.0, 0.0, np.nan],
})

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap');
:root{--bg:#E9ECEE;--sf:#F7F8F9;--ink:#151A1F;--ink2:#4A5560;--ln:#C4CCD3;--asp:#2A323B;--yel:#F0B90B;--grn:#0F6B50;
--fd:'Barlow Condensed','Arial Narrow','Roboto Condensed',sans-serif;--fb:'Barlow','Segoe UI',system-ui,-apple-system,sans-serif;}
@media (prefers-color-scheme: dark){:root{--bg:#161B20;--sf:#1E252C;--ink:#E7EBEE;--ink2:#A3AEB8;--ln:#35414B;--asp:#0E1215;--yel:#F2C230;--grn:#3FB68B;}}
.stApp{background:var(--bg);}
.stApp,.stApp p,.stApp li,.stApp label,.stApp td,.stApp th,.stApp input,.stApp textarea,.stApp button{font-family:var(--fb)!important;}
.stApp h1,.stApp h2,.stApp h3,.stApp h4{font-family:var(--fd)!important;font-weight:600;letter-spacing:0;}
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important;}
header[data-testid="stHeader"]{background:transparent;height:0;}
[data-testid="stSidebar"],[data-testid="collapsedControl"],[data-testid="stSidebarCollapsedControl"]{display:none!important;}
.block-container{max-width:1200px;padding-top:1rem;padding-bottom:2.5rem;}
/* ---- bilah atas ---- */
.top{display:flex;align-items:center;gap:.7rem;padding:.2rem 0 .7rem 0;}
.top-logo{width:36px;height:36px;display:block;}
.top-name{font-family:var(--fd);font-weight:700;font-size:1.75rem;line-height:1;color:var(--ink);}
.top-sub{margin-left:auto;color:var(--ink2);font-size:.88rem;}
.st-key-nav{border-bottom:1px solid var(--ln);margin-bottom:.4rem;}
.st-key-nav .stButton>button{background:transparent;border:none;border-bottom:3px solid transparent;border-radius:0;box-shadow:none;padding:.55rem .2rem .5rem .2rem;color:var(--ink2);}
.st-key-nav .stButton>button p{font-weight:500;font-size:.95rem;color:var(--ink2);}
.st-key-nav .stButton>button:hover{border-bottom-color:var(--ln);background:transparent;}
.st-key-nav .stButton>button[kind="primary"]{background:transparent;border-bottom:3px solid var(--yel);}
.st-key-nav .stButton>button[kind="primary"] p{color:var(--ink);font-weight:600;}
/* ---- hero ---- */
.h-hero{font-family:var(--fd);font-weight:600;font-size:clamp(2.5rem,4.6vw,4rem);line-height:1.02;color:var(--ink);margin:1.4rem 0 1rem 0;}
.p-hero{font-size:1.08rem;line-height:1.6;color:var(--ink2);max-width:33rem;margin:0 0 1.2rem 0;}
.p-note{font-size:.88rem;color:var(--ink2);margin:.9rem 0 0 0;}
.plan{margin:.6rem 0 0 0;}
.plan img,.sheet img{width:100%;display:block;border:1px solid var(--ln);border-radius:3px;}
.sheet{max-width:880px;margin:.4rem auto 0 auto;}
.cap{font-size:.9rem;color:var(--ink2);margin:.6rem 0 0 0;max-width:46rem;}
/* ---- judul bagian ---- */
.h-sec{font-family:var(--fd);font-weight:600;font-size:2rem;line-height:1.1;color:var(--ink);margin:3rem 0 .4rem 0;}
.p-sec{color:var(--ink2);margin:0 0 .8rem 0;max-width:42rem;}
.h-sub{font-family:var(--fd);font-weight:600;font-size:1.35rem;color:var(--ink);margin:1.2rem 0 .3rem 0;}
.ph{border-left:5px solid var(--yel);padding:.2rem 0 .2rem 1rem;margin:1.2rem 0 1.4rem 0;}
.ph-t{font-family:var(--fd);font-weight:600;font-size:2.3rem;line-height:1.05;color:var(--ink);}
.ph-d{color:var(--ink2);margin-top:.3rem;max-width:46rem;}
/* ---- alur: jalan dengan marka putus-putus ---- */
.route{position:relative;padding-left:2.4rem;margin:.3rem 0 0 .3rem;}
.route:before{content:"";position:absolute;left:.7rem;top:.6rem;bottom:.6rem;border-left:3px dashed var(--yel);}
.rs{position:relative;margin:0 0 1.2rem 0;}
.rs:before{content:attr(data-n);position:absolute;left:-2.4rem;top:-.05rem;width:1.55rem;height:1.55rem;border-radius:50%;background:var(--asp);color:#F7F8F9;font-family:var(--fd);font-weight:600;font-size:.95rem;display:flex;align-items:center;justify-content:center;}
.rs b{display:block;font-family:var(--fd);font-weight:600;font-size:1.25rem;color:var(--ink);line-height:1.2;}
.rs span{color:var(--ink2);font-size:.93rem;line-height:1.5;}
/* ---- tabel HTML ---- */
.cmp,.spec,.tb{width:100%;border-collapse:collapse;font-size:.93rem;}
.cmp th,.spec th,.tb th{text-align:left;font-family:var(--fd);font-weight:600;font-size:1.05rem;color:var(--ink);padding:.5rem .7rem;border-bottom:2px solid var(--ink);}
.cmp td,.spec td,.tb td{padding:.55rem .7rem;border-bottom:1px solid var(--ln);vertical-align:top;color:var(--ink);}
.cmp td:first-child,.spec td:first-child{font-weight:600;white-space:nowrap;}
.cmp td:nth-child(2){color:var(--ink2);}
.spec td:last-child{white-space:nowrap;color:var(--ink2);}
.tb td.num,.xl td.num{text-align:right;font-variant-numeric:tabular-nums;}
/* ---- tiruan Excel ---- */
.xl{border:1px solid var(--ln);border-radius:3px;background:var(--sf);overflow:hidden;}
.xl-bar{display:flex;align-items:center;gap:.7rem;padding:.4rem .7rem;border-bottom:1px solid var(--ln);font-size:.9rem;}
.xl-name{border:1px solid var(--ln);padding:.05rem .5rem;border-radius:2px;color:var(--ink);font-weight:600;}
.xl-fx{color:var(--ink2);font-style:italic;}
.xl-f{color:var(--ink);font-family:ui-monospace,Consolas,monospace;font-size:.88rem;}
.xl table{width:100%;border-collapse:collapse;font-size:.9rem;}
.xl th{background:rgba(148,163,184,.18);color:var(--ink2);font-weight:500;text-align:left;padding:.3rem .6rem;border-right:1px solid var(--ln);border-bottom:1px solid var(--ln);}
.xl td{padding:.32rem .6rem;border-right:1px solid var(--ln);border-bottom:1px solid var(--ln);color:var(--ink);}
.xl td.rn{background:rgba(148,163,184,.18);color:var(--ink2);text-align:center;width:2.6rem;}
.xl td.in{color:#1F4FD8;background:rgba(240,185,11,.2);}
.xl td.sel{outline:2px solid var(--grn);outline-offset:-2px;font-weight:600;}
.xl-note{padding:.45rem .7rem;font-size:.85rem;color:var(--ink2);}
/* ---- footer ---- */
.ft{display:grid;grid-template-columns:1.2fr 1.4fr 1.4fr;gap:2rem;margin-top:3.4rem;padding-top:1.4rem;border-top:2px solid var(--ink);}
.ft p{font-size:.88rem;line-height:1.55;color:var(--ink2);margin:.3rem 0 0 0;}
.ft-b{font-family:var(--fd);font-weight:700;font-size:1.5rem;color:var(--ink);}
.ft-h{font-family:var(--fd);font-weight:600;font-size:1.1rem;color:var(--ink);}
.ft-min{margin-top:2.4rem;padding-top:.8rem;border-top:1px solid var(--ln);font-size:.85rem;color:var(--ink2);}
/* ---- komponen streamlit ---- */
[data-testid="stMetric"]{background:var(--sf);border:1px solid var(--ln);border-left:4px solid var(--yel);padding:.7rem .9rem;border-radius:3px;}
[data-testid="stMetricLabel"] p{font-size:.85rem;color:var(--ink2);font-weight:500;}
[data-testid="stMetricValue"]{font-family:var(--fd)!important;font-weight:600;}
[data-testid="stDataFrame"]{border:1px solid var(--ln);border-radius:3px;overflow:hidden;}
[data-testid="stExpander"]{border:1px solid var(--ln);border-radius:3px;background:var(--sf);}
button[data-baseweb="tab"] p{font-size:1rem;font-weight:500;}
.stButton>button,.stDownloadButton>button{border-radius:4px;font-weight:600;padding:.6rem 1.1rem;border:1px solid var(--ink);background:transparent;}
.stButton>button p,.stDownloadButton>button p{color:var(--ink);font-weight:600;}
.stButton>button[kind="primary"],.stDownloadButton>button{background:var(--yel);border:1px solid var(--yel);}
.stButton>button[kind="primary"] p,.stDownloadButton>button p{color:#151A1F;}
.stButton>button:focus-visible,.stDownloadButton>button:focus-visible{outline:3px solid var(--grn);outline-offset:2px;}
div[data-testid="stNumberInput"] input,div[data-baseweb="select"]>div,div[data-baseweb="input"]{border-radius:3px;}
@media(max-width:800px){.ft{grid-template-columns:1fr;}.top-sub{display:none;}.h-sec{font-size:1.7rem;}}
</style>
"""


# ----------------------------------------------------------------- state helper
def _S():
    return st.session_state.setdefault("_v", {})


def V(k):
    return _S().get(k, DEF[k])


def _prep(key):
    if "w_" + key not in st.session_state:
        st.session_state["w_" + key] = V(key)


def in_num(label, key, mn, mx, step, fmt=None, help=None, container=None):
    _prep(key)
    kw = {"format": fmt} if fmt else {}
    x = (container or st).number_input(label, min_value=mn, max_value=mx, step=step, key="w_" + key, help=help, **kw)
    _S()[key] = x
    return x


def in_sel(label, key, opts, radio=False, container=None, help=None):
    if V(key) not in opts:
        _S()[key] = opts[0]
    _prep(key)
    if st.session_state["w_" + key] not in opts:
        st.session_state["w_" + key] = opts[0]
    c = container or st
    x = c.radio(label, opts, key="w_" + key, horizontal=True, help=help) if radio else c.selectbox(label, opts, key="w_" + key, help=help)
    _S()[key] = x
    return x


def in_chk(label, key, help=None, container=None):
    _prep(key)
    x = (container or st).checkbox(label, key="w_" + key, help=help)
    _S()[key] = x
    return x


# ------------------------------------------------------------ data & perhitungan
def param_umum():
    return dict(
        Vr=V("Vr"), Rc=V("Rc"), delta=V("delta"), emax=V("emax") / 100, en=V("en") / 100, Cc=V("Cc"), C1=V("C1"), T=V("T"),
        re=V("re"), Ls_rencana=V("Ls_rencana"), p=V("p"), A=V("A"), b=V("b"), n=int(V("n")), Bn=V("Bn"), kz=V("kz"),
        td_n_plus_1=V("tdn"),
    )


def trase_df():
    return _S().get("trase_df", TRASE_DEFAULT.copy())


def baris_trase(df):
    rows = []
    for _, r in df.iterrows():
        if pd.isna(r.get("X")) or pd.isna(r.get("Y")):
            continue
        vr = r.get("Vr")
        rows.append(dict(
            X=float(r["X"]), Y=float(r["Y"]),
            R=0.0 if pd.isna(r.get("R")) else max(float(r["R"]), 0.0),
            Vr=60.0 if (pd.isna(vr) or vr <= 0) else float(vr),
            Jenis=r["Jenis"] if isinstance(r.get("Jenis"), str) else "Otomatis",
            Ls=0.0 if pd.isna(r.get("Ls")) else max(float(r["Ls"]), 0.0),
        ))
    return rows


def trase_hasil():
    return hitung_trase(baris_trase(trase_df()), V("sta_awal"), param_umum())


def aman_peleb(P, R, vr):
    try:
        return hitung_pelebaran(P, R, vr)
    except ValueError:
        return dict(C=0, b2=0, bp=0, Td=0, Z=0, Bt=P["Bn"], db=0.0, db_raw=0.0, rows=[])


def tikungan_aktif():
    P, sta_pi, jenis_pilih, info = param_umum(), V("sta_pi"), V("jenis"), None
    if V("sumber") == "Ambil dari trase":
        cari = [p for p in trase_hasil()["pi"] if not p["lurus"] and p["nama"] == V("pi_pilih")]
        if cari:
            info = cari[0]
            P, sta_pi, jenis_pilih = dict(info["P"]), info["sta_pi"], info["jenis"]
    hasil = {"FC": hitung_fc(P, sta_pi), "SCS": hitung_scs(P, sta_pi), "SS": hitung_ss(P, sta_pi)}
    saran = rekomendasi(P, hasil)
    terpilih = saran if str(jenis_pilih).startswith("Otomatis") else jenis_pilih
    return dict(P=P, sta_pi=sta_pi, hasil=hasil, saran=saran, terpilih=terpilih, info=info,
                peleb=aman_peleb(P, P["Rc"], P["Vr"]), dasar=hitung_dasar(P))


def df_hasil(rows, teks=False):
    """teks=True -> kolom Nilai jadi string (aman untuk st.dataframe)."""
    df = pd.DataFrame(rows)
    f = (lambda x: f"{x:.4f}" if isinstance(x, (int, float, np.floating)) else str(x)) if teks else \
        (lambda x: round(x, 4) if isinstance(x, (int, float, np.floating)) else x)
    df["Nilai"] = df["Nilai"].apply(f)
    return df


def dms(x):
    d = int(x)
    m = int((x - d) * 60)
    s = ((x - d) * 60 - m) * 60
    return f"{d}°{m:02d}'{s:05.2f}\""


def label_pendek(t):
    return {"FC": "FC", "SCS": "S-C-S", "SS": "S-S"}[t]


# ------------------------------------------------------------------ gambar bantu
# ------------------------------------------------------------------ grafis & HTML
def html(s):
    """Render HTML tanpa baris kosong / indentasi (agar tidak dibaca sebagai blok kode markdown)."""
    st.markdown(re.sub(r"\n\s*", "", s.strip()), unsafe_allow_html=True)


def svg_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def picture(svg_terang, svg_gelap, alt, kelas=""):
    """Gambar SVG yang otomatis ganti versi mengikuti mode terang/gelap."""
    gelap = f'<source media="(prefers-color-scheme: dark)" srcset="{svg_uri(svg_gelap)}">' if svg_gelap else ""
    return f'<picture>{gelap}<img class="{kelas}" src="{svg_uri(svg_terang)}" alt="{alt}"></picture>'


LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="12" fill="#2A323B"/>'
    '<path d="M13 49H29C42 49 49 42 49 29V13" fill="none" stroke="#F7F8F9" stroke-width="9" stroke-linecap="butt"/>'
    '<path d="M13 49H29C42 49 49 42 49 29V13" fill="none" stroke="#F0B90B" stroke-width="2.4" stroke-dasharray="5 4"/>'
    '</svg>'
)


def favicon():
    """Ikon tab browser (PIL). Jatuh ke emoji bila Pillow tidak tersedia."""
    try:
        from PIL import Image, ImageDraw

        S, K = 256, 4
        im = Image.new("RGBA", (S * K, S * K), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, S * K - 1, S * K - 1], radius=48 * K, fill=(42, 50, 59, 255))
        p0, p1, p2, p3 = (52, 196), (116, 196), (196, 168), (196, 52)
        t = np.linspace(0, 1, 60)[:, None]
        # kurva Bezier: lurus ke kanan lalu menikung naik
        c1, c2 = np.array([172, 196]), np.array([196, 172])
        pts = ((1 - t) ** 3) * np.array(p0) + 3 * ((1 - t) ** 2) * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * np.array([196, 52])
        pts = [(float(x) * K, float(y) * K) for x, y in pts]
        d.line(pts, fill=(247, 248, 249, 255), width=36 * K, joint="curve")
        for i in range(0, len(pts) - 1, 4):
            d.line(pts[i:i + 3], fill=(240, 185, 11, 255), width=9 * K)
        return im.resize((S, S), Image.LANCZOS)
    except Exception:
        return "🛣️"


def _pal(gelap):
    if gelap:
        return dict(bg="#1E252C", grid="#2A333B", ink="#E7EBEE", ink2="#A3AEB8", asp="#0E1215", edge="#D5DBE0",
                    yel="#F2C230", grn="#3FB68B", ln="#46525C")
    return dict(bg="#F7F8F9", grid="#E3E7EA", ink="#151A1F", ink2="#4A5560", asp="#2A323B", edge="#F7F8F9",
                yel="#F0B90B", grn="#0F6B50", ln="#B8C1C8")


@st.cache_data(show_spinner=False)
def _demo():
    P = dict(Vr=60.0, emax=.08, en=.02, Cc=.4, C1=1.0, T=3.0, re=0.0, p=7.6, A=2.1, b=2.6, n=2, Bn=7.0, kz=.1,
             td_n_plus_1=True, Rc=180.0, delta=62.0, Ls_rencana=70.0)
    h = hitung_scs(P, 385.0)
    return P, h, bangun_geometri(h, ext=110.0)


def _fm(x):
    return f"{x:.2f}"


@st.cache_data(show_spinner=False)
def svg_plan(gelap=False):
    """Denah jalan (hero): aspal, marka, patok STA tiap 50 m, titik dan dimensi tikungan SCS contoh."""
    c = _pal(gelap)
    P, h, g = _demo()
    v = h["v"]
    W, H = 900, 540
    cen = g["center"]
    lebar = 16.0
    kiri, kanan = tepi_jalan(cen, np.zeros(len(cen)), lebar, 0.0)
    ki2, ka2 = tepi_jalan(cen, np.zeros(len(cen)), lebar - 3.0, 0.0)
    pts = np.vstack([kiri, kanan, [g["O"]], [g["PI"]]])
    mn, mx = pts.min(axis=0), pts.max(axis=0)
    m, mtop, mbot = 84, 70, 112
    s = min((W - 2 * m) / (mx[0] - mn[0]), (H - mtop - mbot) / (mx[1] - mn[1]))
    ox = (W - s * (mx[0] - mn[0])) / 2
    oy = H - mbot - (H - mtop - mbot - s * (mx[1] - mn[1])) / 2

    def T(p):
        return ox + s * (p[0] - mn[0]), oy - s * (p[1] - mn[1])

    def path(arr):
        return "M" + " L".join(f"{T(p)[0]:.1f} {T(p)[1]:.1f}" for p in arr)

    o = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Barlow Condensed,Arial Narrow,Roboto Condensed,Arial,sans-serif">')
    o.append(f'<rect width="{W}" height="{H}" fill="{c["bg"]}"/>')
    for gx in range(0, W + 1, 45):
        o.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{H}" stroke="{c["grid"]}" stroke-width="1"/>')
    for gy in range(0, H + 1, 45):
        o.append(f'<line x1="0" y1="{gy}" x2="{W}" y2="{gy}" stroke="{c["grid"]}" stroke-width="1"/>')
    # badan jalan
    poly = np.vstack([kiri, kanan[::-1]])
    o.append(f'<path d="{path(poly)}Z" fill="{c["asp"]}"/>')
    o.append(f'<path d="{path(ki2)}" fill="none" stroke="{c["edge"]}" stroke-width="1.4" opacity=".9"/>')
    o.append(f'<path d="{path(ka2)}" fill="none" stroke="{c["edge"]}" stroke-width="1.4" opacity=".9"/>')
    o.append(f'<path d="{path(cen)}" fill="none" stroke="{c["yel"]}" stroke-width="2.4" stroke-dasharray="11 8"/>')
    # patok STA tiap 50 m
    seg = np.diff(cen, axis=0)
    ln = np.linalg.norm(seg, axis=1)
    cum = np.concatenate([[0], np.cumsum(ln)])
    for sta in range(0, int(cum[-1]) + 1, 50):
        x = np.interp(sta, cum, cen[:, 0])
        y = np.interp(sta, cum, cen[:, 1])
        i = min(max(np.searchsorted(cum, sta, side="right") - 1, 0), len(seg) - 1)
        d = seg[i] / max(ln[i], 1e-9)
        n = np.array([-d[1], d[0]])
        a, b = T(np.array([x, y]) + n * (lebar / 2 + 4)), T(np.array([x, y]) - n * (lebar / 2 + 4))
        o.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{c["ink"]}" stroke-width="1.4"/>')
        lab = T(np.array([x, y]) - n * (lebar / 2 + 15))
        o.append(f'<text x="{lab[0]:.1f}" y="{lab[1] + 4:.1f}" text-anchor="middle" font-size="12" fill="{c["ink2"]}">{sta // 1000}+{sta % 1000:03d}</text>')
    # jari-jari dan pusat
    O, PI, ST = g["O"], g["PI"], g["ST"]
    for q in (g["SC"], g["CS"]):
        a, b = T(O), T(q)
        o.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{c["ink2"]}" stroke-width="1.1" stroke-dasharray="6 5"/>')
    a, b = T(O), T(g["CS"])
    o.append(f'<text x="{(a[0] + b[0]) / 2 + 8:.1f}" y="{(a[1] + b[1]) / 2 - 6:.1f}" font-size="15" font-weight="600" fill="{c["ink"]}">R</text>')
    pO = T(O)
    o.append(f'<circle cx="{pO[0]:.1f}" cy="{pO[1]:.1f}" r="3.4" fill="{c["ink"]}"/><text x="{pO[0] - 16:.1f}" y="{pO[1] - 8:.1f}" font-size="15" font-weight="600" fill="{c["ink"]}">O</text>')
    # titik tikungan (label di sisi dalam jalan, diukur dari normal)
    for nm, q in (("TS", np.array([0.0, 0.0])), ("SC", g["SC"]), ("CS", g["CS"]), ("ST", ST)):
        pq = T(q)
        o.append(f'<circle cx="{pq[0]:.1f}" cy="{pq[1]:.1f}" r="4" fill="{c["yel"]}" stroke="{c["ink"]}" stroke-width="1.4"/>')
        j = int(np.argmin(np.linalg.norm(cen - q, axis=1)))
        dd = seg[min(j, len(seg) - 1)] / max(ln[min(j, len(seg) - 1)], 1e-9)
        nn = np.array([-dd[1], dd[0]])
        lp = T(q + nn * (lebar / 2 + 13))
        o.append(f'<text x="{lp[0]:.1f}" y="{lp[1] + 5:.1f}" text-anchor="middle" font-size="16" font-weight="600" fill="{c["ink"]}">{nm}</text>')
    pP = T(PI)
    o.append(f'<circle cx="{pP[0]:.1f}" cy="{pP[1]:.1f}" r="4" fill="{c["bg"]}" stroke="{c["ink"]}" stroke-width="1.6"/>')
    o.append(f'<text x="{pP[0] + 10:.1f}" y="{pP[1] + 22:.1f}" font-size="16" font-weight="600" fill="{c["ink"]}">PI</text>')
    # dimensi Ts di bawah jalan
    a, b = T(np.array([0.0, 0.0])), pP
    yd = a[1] + s * lebar / 2 + 60
    for xx in (a[0], b[0]):
        o.append(f'<line x1="{xx:.1f}" y1="{a[1] + s * lebar / 2 + 6:.1f}" x2="{xx:.1f}" y2="{yd + 6:.1f}" stroke="{c["ink"]}" stroke-width="1"/>')
        o.append(f'<line x1="{xx - 5:.1f}" y1="{yd + 5:.1f}" x2="{xx + 5:.1f}" y2="{yd - 5:.1f}" stroke="{c["ink"]}" stroke-width="1.6"/>')
    o.append(f'<line x1="{a[0]:.1f}" y1="{yd:.1f}" x2="{b[0]:.1f}" y2="{yd:.1f}" stroke="{c["ink"]}" stroke-width="1.1"/>')
    o.append(f'<text x="{(a[0] + b[0]) / 2:.1f}" y="{yd - 8:.1f}" text-anchor="middle" font-size="15" fill="{c["ink"]}">Ts = {_fm(v["Ts"])} m</text>')
    # sudut belok di PI
    r = 52
    dl = math.radians(P["delta"])
    p0 = (pP[0] + r, pP[1])
    p1 = (pP[0] + r * math.cos(dl), pP[1] - r * math.sin(dl))
    o.append(f'<line x1="{pP[0]:.1f}" y1="{pP[1]:.1f}" x2="{pP[0] + r + 38:.1f}" y2="{pP[1]:.1f}" stroke="{c["ink2"]}" stroke-width="1.1" stroke-dasharray="6 5"/>')
    o.append(f'<path d="M{p0[0]:.1f} {p0[1]:.1f} A{r} {r} 0 0 0 {p1[0]:.1f} {p1[1]:.1f}" fill="none" stroke="{c["ink"]}" stroke-width="1.4"/>')
    am = dl / 2
    o.append(f'<text x="{pP[0] + (r + 17) * math.cos(am):.1f}" y="{pP[1] - (r + 17) * math.sin(am) + 5:.1f}" font-size="16" font-weight="600" fill="{c["ink"]}">Δ = {P["delta"]:g}°</text>')
    # blok data
    rows = [("R", f"{P['Rc']:g} m"), ("Ls", f"{v['Ls']:g} m"), ("Lc", f"{_fm(v['Lc'])} m"), ("Es", f"{_fm(v['Es'])} m")]
    bx, by, bw = 28, 28, 168
    o.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{26 + 22 * len(rows)}" rx="3" fill="{c["bg"]}" stroke="{c["ln"]}"/>')
    o.append(f'<text x="{bx + 12}" y="{by + 20}" font-size="14" font-weight="600" fill="{c["ink"]}">Tikungan S-C-S contoh</text>')
    for i, (k, val) in enumerate(rows):
        yy = by + 44 + 22 * i
        o.append(f'<line x1="{bx}" y1="{yy - 15}" x2="{bx + bw}" y2="{yy - 15}" stroke="{c["ln"]}"/>')
        o.append(f'<text x="{bx + 12}" y="{yy}" font-size="14" fill="{c["ink2"]}">{k}</text>')
        o.append(f'<text x="{bx + bw - 12}" y="{yy}" text-anchor="end" font-size="14" font-weight="600" fill="{c["ink"]}">{val}</text>')
    o.append('</svg>')
    return "".join(o)


@st.cache_data(show_spinner=False)
def svg_lembar():
    """Tiruan lembar DXF A3 (isi mengikuti keluaran asli): skema, dimensi, tabel data."""
    P, h, g = _demo()
    v = h["v"]
    pel = hitung_pelebaran(P, P["Rc"], P["Vr"])
    W, H = 1000, 707
    ink, ln, red, mag, ora, gry = "#1B2127", "#9AA5AE", "#D62728", "#B5179E", "#E8730C", "#B7C0C7"
    cen = g["center"]
    kiri, kanan = tepi_jalan(cen, g["t"], P["Bn"], pel["db"])
    pts = np.vstack([kiri, kanan, [g["O"]], [g["PI"]]])
    mn, mx = pts.min(axis=0), pts.max(axis=0)
    ax0, ax1, ay0, ay1 = 52, 700, 118, 620
    s = min((ax1 - ax0 - 50) / (mx[0] - mn[0]), (ay1 - ay0 - 70) / (mx[1] - mn[1]))
    ox = (ax0 + ax1) / 2 - s * (mx[0] - mn[0]) / 2
    oy = (ay0 + ay1) / 2 + s * (mx[1] - mn[1]) / 2 - 18

    def T(p):
        return ox + s * (p[0] - mn[0]), oy - s * (p[1] - mn[1])

    def path(arr):
        return "M" + " L".join(f"{T(p)[0]:.1f} {T(p)[1]:.1f}" for p in arr)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Barlow,Arial,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
         f'<rect x="14" y="14" width="{W - 28}" height="{H - 28}" fill="none" stroke="{ink}" stroke-width="2.4"/>']
    o.append(f'<path d="{path(kiri)}" fill="none" stroke="{gry}" stroke-width="1.2"/>')
    o.append(f'<path d="{path(kanan)}" fill="none" stroke="{gry}" stroke-width="1.2"/>')
    o.append(f'<path d="{path(cen)}" fill="none" stroke="{ink}" stroke-width="1" opacity=".55"/>')
    o.append(f'<path d="{path(g["curva"])}" fill="none" stroke="{red}" stroke-width="3"/>')
    O, PI = g["O"], g["PI"]
    for q in (g["SC"], g["CS"], np.array([v["K"], 0.0])):
        a, b = T(O), T(q)
        o.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{mag}" stroke-width="1" stroke-dasharray="6 4"/>')
    for nm, q, off in (("TS", np.array([0.0, 0.0]), (-26, -8)), ("SC", g["SC"], (6, 18)), ("CS", g["CS"], (8, 4)),
                       ("ST", g["ST"], (8, 4)), ("PI", PI, (8, 18)), ("O", O, (8, -6))):
        pq = T(q)
        o.append(f'<circle cx="{pq[0]:.1f}" cy="{pq[1]:.1f}" r="3" fill="#fff" stroke="{ink}" stroke-width="1.3"/>')
        o.append(f'<text x="{pq[0] + off[0]:.1f}" y="{pq[1] + off[1]:.1f}" font-size="12" font-weight="600" fill="{ink}">{nm}</text>')
    a0, pP = T(np.array([0.0, 0.0])), T(PI)
    for k_, (lab, x1, off) in enumerate((("K", v["K"], 24), ("Xc", v["Xc"], 44), ("Ts", v["Ts"], 64))):
        b = T(np.array([x1, 0.0]))
        yd = a0[1] + off
        o.append(f'<line x1="{a0[0]:.1f}" y1="{a0[1]:.1f}" x2="{a0[0]:.1f}" y2="{yd + 4:.1f}" stroke="{ora}" stroke-width=".9"/>')
        o.append(f'<line x1="{b[0]:.1f}" y1="{b[1]:.1f}" x2="{b[0]:.1f}" y2="{yd + 4:.1f}" stroke="{ora}" stroke-width=".9"/>')
        o.append(f'<line x1="{a0[0]:.1f}" y1="{yd:.1f}" x2="{b[0]:.1f}" y2="{yd:.1f}" stroke="{ora}" stroke-width="1"/>')
        for xx in (a0[0], b[0]):
            o.append(f'<line x1="{xx - 4:.1f}" y1="{yd + 4:.1f}" x2="{xx + 4:.1f}" y2="{yd - 4:.1f}" stroke="{ora}" stroke-width="1.4"/>')
        o.append(f'<text x="{(a0[0] + b[0]) / 2:.1f}" y="{yd - 5:.1f}" text-anchor="middle" font-size="11" fill="{ora}">{lab} = {v["K"] if lab == "K" else (v["Xc"] if lab == "Xc" else v["Ts"]):.4f}</text>')
    # tabel kanan
    def tabel(x, y, jd, rows_):
        w, rh = 246, 21
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{rh * (len(rows_) + 1)}" fill="none" stroke="{ink}" stroke-width="1.2"/>')
        o.append(f'<text x="{x + w / 2}" y="{y + 15}" text-anchor="middle" font-size="12" font-weight="700" fill="{ink}">{jd}</text>')
        for i, (k_, val) in enumerate(rows_, start=1):
            yy = y + rh * i
            o.append(f'<line x1="{x}" y1="{yy}" x2="{x + w}" y2="{yy}" stroke="{ln}"/>')
            o.append(f'<text x="{x + 8}" y="{yy + 15}" font-size="11.5" fill="{ink}">{k_}</text>')
            o.append(f'<text x="{x + w - 8}" y="{yy + 15}" text-anchor="end" font-size="11.5" fill="{ink}">{val}</text>')
        return y + rh * (len(rows_) + 1)

    ts = 385.0 - v["Ts"]
    yb = tabel(730, 40, "DATA TIKUNGAN SCS", [
        ("Kecepatan rencana Vr", f"{P['Vr']:g} km/jam"), ("Radius R", f"{P['Rc']:.2f} m"), ("Sudut belok Δ", f"{P['delta']:.2f}°"),
        ("Ls", f"{v['Ls']:.4f} m"), ("θs", f"{v['ths']:.4f}°"), ("θc", f"{v['thc']:.4f}°"), ("Lc", f"{v['Lc']:.4f} m"),
        ("K", f"{v['K']:.4f} m"), ("Es", f"{v['Es']:.4f} m"), ("Ts", f"{v['Ts']:.4f} m")])
    yb = tabel(730, yb + 14, "PELEBARAN PERKERASAN", [
        ("Lebar normal Bn", f"{P['Bn']:.2f} m"), ("Lebar di tikungan Bt", f"{pel['Bt']:.4f} m"), ("Pelebaran Δb", f"{pel['db']:.4f} m")])
    tabel(730, yb + 14, "STASIONING", [
        ("TS", fmt_sta(ts)), ("SC", fmt_sta(ts + v["Ls"])), ("PI", fmt_sta(385.0)),
        ("CS", fmt_sta(ts + v["Ls"] + v["Lc"])), ("ST", fmt_sta(ts + 2 * v["Ls"] + v["Lc"]))])
    # strip bawah
    o.append(f'<rect x="14" y="{H - 62}" width="{W - 28}" height="48" fill="none" stroke="{ink}" stroke-width="2"/>')
    o.append(f'<line x1="{W - 250}" y1="{H - 62}" x2="{W - 250}" y2="{H - 14}" stroke="{ink}" stroke-width="1.6"/>')
    o.append(f'<text x="34" y="{H - 31}" font-size="20" font-weight="700" fill="{ink}">PI-1 - S-C-S</text>')
    o.append(f'<text x="{W - 125}" y="{H - 31}" text-anchor="middle" font-size="18" font-weight="600" fill="{ink}">SKALA 1 : 800</text>')
    o.append('</svg>')
    return "".join(o)


def excel_mock():
    """Cuplikan sheet Parameter: sel hasil berisi rumus."""
    P, h, g = _demo()
    v = h["v"]
    baris_ = [
        ("5", "Sudut belok", "Δ", "input", f"{P['delta']:.4f}", "in"),
        ("6", "Radius tikungan rencana", "Rc", "input", f"{P['Rc']:.2f}", "in"),
        ("24", "Pergeseran busur", "P", "Yc − R(1 − cos θs)", f"{v['P']:.4f}", ""),
        ("25", "Absis pusat busur", "K", "Xc − R·sin θs", f"{v['K']:.4f}", ""),
        ("26", "Jarak luar PI ke busur", "Es", "(R+P)/cos(Δ/2) − R", f"{v['Es']:.4f}", ""),
        ("27", "Jarak TS ke PI", "Ts", "(R+P)·tan(Δ/2) + K", f"{v['Ts']:.4f}", "sel"),
    ]
    trs = ""
    for no, a, b, c_, d, kls in baris_:
        trs += f'<tr><td class="rn">{no}</td><td>{a}</td><td>{b}</td><td>{c_}</td><td class="num {kls}">{d}</td></tr>'
    return (
        '<div class="xl"><div class="xl-bar"><span class="xl-name">D27</span><span class="xl-fx">fx</span>'
        '<span class="xl-f">=($D$6+$D$24)*TAN(RADIANS($D$5/2))+$D$25</span></div>'
        '<table><tr><th></th><th>A  Parameter</th><th>B  Simbol</th><th>C  Rumus</th><th>D  Nilai</th></tr>' + trs + '</table>'
        '<div class="xl-note">Sel biru = input. Sel hitam = rumus Excel yang menghitung otomatis.</div></div>'
    )


def sta_mock():
    """Tabel STA nyata dari data contoh trase."""
    P0 = dict(emax=.08, en=.02, Cc=.4, C1=1.0, T=3.0, re=0.0, p=7.6, A=2.1, b=2.6, n=2, Bn=7.0, kz=0.1, td_n_plus_1=True)
    tr = hitung_trase(baris_trase(TRASE_DEFAULT), 0.0, P0)
    trs = ""
    for p in tr["pi"]:
        trs += (f'<tr><td>{p["nama"]}</td><td>{p["jenis"]}</td><td class="num">{p["delta"]:.2f}° {p["arah"].lower()}</td>'
                f'<td class="num">{fmt_sta(p["sta_ts"])}</td><td class="num">{fmt_sta(p["sta_pi"])}</td><td class="num">{fmt_sta(p["sta_st"])}</td></tr>')
    return (
        '<table class="tb"><tr><th>PI</th><th>Jenis</th><th>Sudut belok</th><th>STA TS</th><th>STA PI</th><th>STA ST</th></tr>'
        + trs + '</table>'
        f'<div class="xl-note">Data contoh bawaan. Panjang trase {tr["panjang"]:,.2f} m, berakhir di STA {fmt_sta(tr["sta_akhir"])}.</div>'
    )


# ------------------------------------------------------------------ gambar matplotlib HD
_KERTAS, _INK, _INK2, _ASP, _KUN, _HIJ = "#F7F8F9", "#151A1F", "#4A5560", "#2A323B", "#F0B90B", "#0F6B50"


@st.cache_data(show_spinner=False)
def skema_png(tipe):
    """Skema contoh tikungan untuk halaman materi dan hasil hitung (PNG resolusi tinggi)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    base = dict(Vr=60.0, emax=.08, en=.02, Cc=.4, C1=1.0, T=3.0, re=0.0, p=7.6, A=2.1, b=2.6, n=2, Bn=7.0, kz=.1, td_n_plus_1=True)
    if tipe == "FC":
        h = hitung_fc(dict(base, Rc=120.0, delta=50.0, Ls_rencana=0.0), 0)
    elif tipe == "SCS":
        h = hitung_scs(dict(base, Rc=100.0, delta=75.0, Ls_rencana=40.0), 0)
    else:
        h = hitung_ss(dict(base, Rc=100.0, delta=50.0, Ls_rencana=0.0), 0)
    g = bangun_geometri(h, ext=35.0)
    fig, ax = plt.subplots(figsize=(5.6, 4.5), dpi=220)
    fig.patch.set_facecolor(_KERTAS)
    ax.set_facecolor(_KERTAS)
    PI, O, ST = g["PI"], g["O"], g["ST"]
    ax.plot([-35, PI[0]], [0, 0], color="#8A96A1", lw=1.3)
    ax.plot([PI[0], ST[0] + 35 * g["dirB"][0]], [PI[1], ST[1] + 35 * g["dirB"][1]], color="#8A96A1", lw=1.3)
    ax.plot(g["curva"][:, 0], g["curva"][:, 1], color=_HIJ, lw=3.4, solid_capstyle="butt")
    ax.plot([PI[0], O[0]], [PI[1], O[1]], ls=(0, (6, 3, 1, 3)), color="#98A3AD", lw=0.9)
    if tipe == "FC":
        marks = [("TC", g["TC"]), ("CT", g["CT"])]
    elif tipe == "SCS":
        marks = [("TS", g["TS"]), ("SC", g["SC"]), ("CS", g["CS"]), ("ST", g["ST"])]
    else:
        marks = [("TS", g["TS"]), ("SS", g["SC"]), ("ST", g["ST"])]
    for _, p in marks:
        ax.plot([O[0], p[0]], [O[1], p[1]], ls=(0, (5, 4)), color="#B0BAC3", lw=0.9)
    for nm, p in marks + [("PI", PI), ("O", O)]:
        ax.plot(*p, "o", color=_KUN, mec=_INK, mew=1.2, ms=5.5, zorder=5)
        ax.annotate(nm, p, textcoords="offset points", xytext=(7, 6), fontsize=11, fontweight="bold", color=_INK)
    ax.set_aspect("equal")
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=_KERTAS)
    plt.close(fig)
    return buf.getvalue()


def trase_png(tr):
    """Gambar trase: jalan, patok STA tiap 100 m, titik PI (PNG resolusi tinggi)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10.5, 5.6), dpi=200)
    fig.patch.set_facecolor(_KERTAS)
    ax.set_facecolor(_KERTAS)
    xs = [t[1] for t in tr["titik"]]
    ys = [t[2] for t in tr["titik"]]
    ax.plot(xs, ys, color="#98A3AD", lw=1, ls=(0, (6, 4)), zorder=1)
    pts = [np.array([xs[0], ys[0]])]
    for pi in tr["pi"]:
        if pi["lurus"] or (pi["jenis"] == "SCS" and pi["h"]["v"]["thc"] <= 0):
            pts.append(np.array(pi["xy"]))
        else:
            pts.extend(list(kurva_global(pi)))
    pts.append(np.array([xs[-1], ys[-1]]))
    arr = np.array(pts)
    ax.plot(arr[:, 0], arr[:, 1], color=_ASP, lw=7, solid_capstyle="butt", zorder=2)
    ax.plot(arr[:, 0], arr[:, 1], color=_KUN, lw=1.2, ls=(0, (6, 4)), zorder=3)
    seg = np.diff(arr, axis=0)
    ln = np.linalg.norm(seg, axis=1)
    cum = np.concatenate([[0], np.cumsum(ln)])
    sta0 = tr["tabel_sta"][0][1]
    first = int(np.ceil(sta0 / 100.0) * 100)
    for sta in range(first, int(sta0 + cum[-1]) + 1, 100):
        sl = sta - sta0
        x, y = np.interp(sl, cum, arr[:, 0]), np.interp(sl, cum, arr[:, 1])
        i = min(max(np.searchsorted(cum, sl, side="right") - 1, 0), len(seg) - 1)
        d = seg[i] / max(ln[i], 1e-9)
        n = np.array([-d[1], d[0]])
        sp = max(np.ptp(xs), np.ptp(ys)) * 0.022
        ax.plot([x - n[0] * sp * .7, x + n[0] * sp * .7], [y - n[1] * sp * .7, y + n[1] * sp * .7], color=_INK, lw=1.1, zorder=4)
        ax.text(x - n[0] * sp * 2.0, y - n[1] * sp * 2.0, f"{sta // 1000}+{sta % 1000:03d}", fontsize=7, color=_INK2, ha="center", va="center")
    for nama, x, y in tr["titik"]:
        ax.plot(x, y, "o", ms=5.5, color=_KERTAS, mec=_INK, mew=1.5, zorder=6)
        ax.annotate(nama, (x, y), textcoords="offset points", xytext=(7, 8), fontsize=9.5, fontweight="bold", color=_INK)
    ax.set_aspect("equal")
    ax.grid(color="#DDE2E6", lw=.6)
    for sp_ in ax.spines.values():
        sp_.set_color("#C3CBD2")
    ax.tick_params(colors=_INK2, labelsize=8)
    ax.set_xlabel("X / Easting (m)", color=_INK2, fontsize=9)
    ax.set_ylabel("Y / Northing (m)", color=_INK2, fontsize=9)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=_KERTAS)
    plt.close(fig)
    return buf.getvalue()


def pratinjau_png(doc):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    fig = plt.figure(figsize=(16, 11.5))
    ax = fig.add_axes([0, 0, 1, 1])
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(doc.modelspace(), finalize=True)
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=130)
    plt.close(fig)
    return out.getvalue()


# =============================================================================
#  HALAMAN 1 : BERANDA
# =============================================================================
# =============================================================================
#  HALAMAN 2 : MATERI DASAR
# =============================================================================
def halaman_materi():
    judul_halaman("Materi Dasar Alinyemen Horizontal", "Ringkasan teori yang dipakai di aplikasi ini. Rumusnya sama dengan menu hitung dan Excel.")
    tabs = st.tabs(["Pengantar", "Jenis Tikungan", "Rumus Dasar", "Lengkung Peralihan", "Pelebaran",
                    "Jarak Pandang", "Azimut, Jarak & STA", "Istilah", "Referensi"])

    with tabs[0]:
        st.subheader("Apa itu alinyemen horizontal?")
        st.write(
            "Alinyemen horizontal adalah proyeksi sumbu jalan pada bidang horizontal (tampak atas atau denah). "
            "Bentuknya tersusun dari **bagian lurus (tangen)** dan **bagian lengkung (tikungan)** yang dihubungkan "
            "di titik **PI** (Point of Intersection)."
        )
        st.markdown(
            "- **Tujuan:** kendaraan bisa melewati tikungan dengan aman dan nyaman pada kecepatan rencana.\n"
            "- **Dipengaruhi oleh:** kecepatan rencana (Vr), kelas jalan, topografi, superelevasi (e), dan koefisien gesek (f).\n"
            "- **Data awal di lapangan:** koordinat titik awal (A), titik-titik PI, dan titik akhir (B).\n"
            "- **Yang dicari:** jarak antar-titik, azimut, sudut belok (Δ), jenis dan dimensi tikungan, STA, serta gambar."
        )
        st.subheader("Gaya pada tikungan")
        st.write(
            "Saat berbelok, kendaraan terdorong keluar oleh gaya sentrifugal. Gaya ini dilawan oleh "
            "**gesekan ban** (f) dan **kemiringan melintang jalan / superelevasi** (e). Semakin kecil radius, semakin "
            "besar gaya yang harus dilawan, dan itulah sebabnya ada **radius minimum**."
        )

    with tabs[1]:
        st.subheader("Tiga jenis tikungan")
        c1, c2, c3 = st.columns(3)
        c1.image(skema_png("FC"), caption="Full Circle (FC)", use_container_width=True)
        c2.image(skema_png("SCS"), caption="Spiral-Circle-Spiral (SCS)", use_container_width=True)
        c3.image(skema_png("SS"), caption="Spiral-Spiral (SS)", use_container_width=True)
        st.markdown("""
| | **FC** | **SCS** | **SS** |
|---|---|---|---|
| Bentuk | Satu busur lingkaran | Spiral – busur – spiral | Spiral – spiral (tanpa busur) |
| Titik penting | TC, CT | TS, SC, CS, ST | TS, SS, ST |
| Dipakai bila | Radius besar (≥ R min FC) | Radius sedang/kecil, ada ruang untuk busur | Δ kecil dan R kecil, busur lingkaran terlalu pendek |
| Syarat | R ≥ R min FC | θc > 0 dan Lc ≥ 20 m | Ls = θs·π·R/90, dengan θs = Δ/2 |
""")
        with st.expander("Rumus Full Circle (FC)"):
            st.latex(r"T_c = R\,\tan\tfrac{\Delta}{2}\qquad E_c = T_c\,\tan\tfrac{\Delta}{4}\qquad L_c = \frac{\Delta\,\pi\,R}{180}")
        with st.expander("Rumus Spiral-Circle-Spiral (SCS)", expanded=True):
            st.latex(r"\theta_s = \frac{90\,L_s}{\pi R}\qquad \theta_c = \Delta - 2\theta_s\qquad L_c = \frac{\theta_c\,\pi R}{180}")
            st.latex(r"X_c = L_s - \frac{L_s^3}{40R^2}\qquad Y_c = \frac{L_s^2}{6R}")
            st.latex(r"P = Y_c - R(1-\cos\theta_s)\qquad K = X_c - R\sin\theta_s")
            st.latex(r"T_s = (R+P)\tan\tfrac{\Delta}{2} + K\qquad E_s = \frac{R+P}{\cos\frac{\Delta}{2}} - R\qquad L_{tot} = L_c + 2L_s")
        with st.expander("Rumus Spiral-Spiral (SS)"):
            st.latex(r"\theta_s = \tfrac{\Delta}{2}\qquad L_s = \frac{\theta_s\,\pi R}{90}\qquad L_c = 0\qquad L_{tot}=2L_s")
            st.write("Nilai Xs, Ys, P, K, Ts, dan Es memakai rumus yang sama dengan SCS.")
        st.subheader("Radius minimum tikungan FC (tanpa lengkung peralihan)")
        st.dataframe(pd.DataFrame({"Vr (km/jam)": list(RMIN_FC), "R min FC (m)": list(RMIN_FC.values())}),
                     hide_index=True, use_container_width=True)

    with tabs[2]:
        st.subheader("Koefisien gesek dan radius minimum")
        st.latex(r"f = -0{,}00065\,V_r + 0{,}192 \quad (V_r < 80)\qquad f = -0{,}00125\,V_r + 0{,}24 \quad (80 \le V_r \le 112)")
        st.latex(r"R_{min} = \frac{V_r^2}{127\,(e_{maks} + f)}")
        st.write(
            "Radius yang direncanakan harus **lebih besar atau sama dengan R min**. Superelevasi maksimum (e maks) umumnya "
            "8–10% untuk jalan antarkota dan lebih kecil di perkotaan; ikuti pedoman yang dipakai."
        )
        st.subheader("Superelevasi")
        st.write(
            "Superelevasi adalah kemiringan melintang jalan di tikungan untuk membantu melawan gaya sentrifugal. "
            "Pada tikungan SCS, perubahan kemiringan dari normal (en) ke penuh (e) dilakukan sepanjang spiral. "
            "Pada FC dilakukan di bagian lurus sebelum TC dan sebagian di lengkung. "
            "Aplikasi menggambar diagramnya di menu Tikungan dan menyertakannya di file DXF dan Excel."
        )

    with tabs[3]:
        st.subheader("Panjang lengkung peralihan (Ls)")
        st.write("Ls minimum diambil dari nilai **terbesar** dari empat kriteria, lalu dibulatkan ke atas (kelipatan 5 m).")
        st.markdown("**1. Rumus Shortt (laporan)**")
        st.latex(r"L_{s1} = \frac{0{,}0214\,V_r^3}{R\,C_1}")
        st.markdown("**2. Waktu tempuh maksimum (T = 3 detik)**")
        st.latex(r"L_{s2} = \frac{V_r}{3{,}6}\,T")
        st.markdown("**3. Antisipasi gaya sentrifugal (Shortt dimodifikasi)**")
        st.latex(r"L_{s3} = \frac{0{,}022\,V_r^3}{R\,C} - \frac{2{,}727\,V_r\,e}{C}")
        st.markdown("**4. Landai relatif**")
        st.latex(r"L_{s4} = \frac{(e_{maks}-e_n)\,V_r}{3{,}6\,r_e}")
        st.write("Dengan C = 0,4 m/det³, T = 3 detik, e n = 2%, r e = 0,025 (Vr ≤ 70) atau 0,035 (Vr ≥ 80) sebagai nilai awal.")

    with tabs[4]:
        st.subheader("Pelebaran perkerasan di tikungan")
        st.write(
            "Di tikungan, kendaraan tidak menempati lintasan yang sama dengan bagian lurus (roda belakang mengikuti "
            "lintasan lebih ke dalam), sehingga lebar perkerasan perlu ditambah."
        )
        st.latex(r"b'' = R - \sqrt{R^2 - p^2}\qquad b' = b + b''\qquad C = \tfrac{B_n}{2} - b")
        st.latex(r"T_d = \sqrt{R^2 + A(2p + A)} - R\qquad Z = \frac{0{,}1\,V_r}{\sqrt{R}}")
        st.latex(r"B_t = n\,(b' + C) + (n\pm1)\,T_d + Z\qquad \Delta b = B_t - B_n")
        st.write("p = jarak gandar, A = tonjolan depan, b = lebar kendaraan, n = jumlah lajur, Bn = lebar normal. "
                 "Jika Δb ≤ 0 pelebaran tidak diperlukan.")

    with tabs[5]:
        st.subheader("Jarak pandang henti (JPH)")
        st.latex(r"JPH = \frac{V_r\,t}{3{,}6} + \frac{V_r^2}{2\cdot 3{,}6^2\cdot 9{,}81\left(\frac{a}{9{,}81} \pm G\right)}")
        st.write("t = waktu reaksi (≈ 2,5 detik), a = perlambatan (≈ 3,4 m/det²), G = kelandaian (+ tanjakan, − turunan).")
        st.subheader("Jarak pandang mendahului (JPM)")
        st.latex(r"JPM = d_1 + d_2 + d_3 + d_4")
        st.latex(r"d_1 = 0{,}278\,T_1\left(V_r - m + \tfrac{a\,T_1}{2}\right)\quad d_2 = 0{,}278\,V_r\,T_2\quad d_4 = \tfrac{2}{3}d_2")
        st.latex(r"T_1 = 2{,}12 + 0{,}026V_r\quad T_2 = 6{,}56 + 0{,}048V_r\quad a = 2{,}052 + 0{,}0036V_r")
        st.write("d₃ = jarak bebas antara kendaraan (30–100 m). m = selisih kecepatan kendaraan yang disiap (≈ 15 km/jam).")
        st.dataframe(pd.DataFrame({"Vr (km/jam)": list(JPM_STD), "JPH min (m)": [JPH_STD[k] for k in JPM_STD],
                                   "JPM min (m)": list(JPM_STD.values())}), hide_index=True, use_container_width=True)

    with tabs[6]:
        st.subheader("Dari koordinat ke STA")
        st.markdown("**1. Jarak dan azimut** (X = Easting, Y = Northing; azimut diukur dari utara searah jarum jam)")
        st.latex(r"d = \sqrt{(X_2-X_1)^2 + (Y_2-Y_1)^2}\qquad \alpha = \operatorname{atan2}(X_2-X_1,\;Y_2-Y_1)")
        st.markdown("**2. Sudut belok di PI**")
        st.latex(r"\Delta = |\alpha_2 - \alpha_1|\quad(\text{dinormalkan ke } 0\text{–}180^\circ)")
        st.write("Jika α₂ − α₁ positif, arahnya belok kanan; jika negatif, belok kiri.")
        st.markdown("**3. Stasioning berantai**")
        st.latex(r"STA_{PI,k} = STA_{ST,k-1} + d_{k-1,k} - T_{s,k-1}")
        st.latex(r"STA_{TS,k} = STA_{PI,k} - T_{s,k}\qquad STA_{ST,k} = STA_{TS,k} + L_{tot,k}")
        st.info(
            "**Kenapa STA tidak boleh ditebak?** Panjang jalan sebenarnya lebih pendek dari jumlah jarak PI-ke-PI, karena "
            "di tiap tikungan jalan memotong sudut: sepanjang Ts di sisi masuk dan Ts di sisi keluar diganti oleh lengkung "
            "sepanjang Ltot. Itu sebabnya STA tiap PI bergantung pada hasil tikungan sebelumnya."
        )
        st.caption("Format STA: 1+246,75 berarti km 1 + 246,75 m = 1.246,75 m dari awal.")

    with tabs[7]:
        st.subheader("Istilah dan simbol")
        st.dataframe(pd.DataFrame([
            ("PI", "Point of Intersection, titik potong dua tangen"), ("Δ", "Sudut belok (sudut luar) di PI"),
            ("TC / CT", "Awal / akhir busur pada FC"), ("TS / ST", "Awal spiral / akhir spiral"),
            ("SC / CS", "Spiral ke busur / busur ke spiral"), ("SS", "Titik pertemuan dua spiral pada tikungan S-S"),
            ("O", "Titik pusat busur lingkaran"), ("R", "Radius busur lingkaran"),
            ("Ls", "Panjang lengkung peralihan (spiral)"), ("Lc", "Panjang busur lingkaran"),
            ("θs", "Sudut spiral"), ("θc", "Sudut busur lingkaran"),
            ("Ts / Tc", "Jarak TS (atau TC) ke PI sepanjang tangen"), ("Es / Ec", "Jarak PI ke busur (jarak luar)"),
            ("P", "Pergeseran busur ke dalam akibat spiral"), ("K", "Absis titik pusat busur dari TS"),
            ("Vr", "Kecepatan rencana"), ("e / f", "Superelevasi / koefisien gesek melintang"),
            ("JPH / JPM", "Jarak pandang henti / mendahului"), ("STA", "Stasioning (jarak dari awal trase)"),
        ], columns=["Simbol", "Arti"]), hide_index=True, use_container_width=True)

    with tabs[8]:
        st.subheader("Referensi")
        st.markdown(
            "- Direktorat Jenderal Bina Marga, *Tata Cara Perencanaan Geometrik Jalan Antar Kota* (TPGJAK), No. 038/TBM/1997.\n"
            "- Direktorat Jenderal Bina Marga, *Pedoman Desain Geometrik Jalan* (2021).\n"
            "- Sukirman, S. (1999). *Dasar-Dasar Perencanaan Geometrik Jalan*. Bandung: Nova.\n"
        )
        st.warning("Selalu cocokkan nilai (R min, e maks, jarak pandang, dll.) dengan edisi pedoman yang dipakai pada proyek Anda.")


# =============================================================================
#  HALAMAN 3 : JARAK, AZIMUT & STA
# =============================================================================
def _muat_contoh():
    st.session_state["trase_base"] = TRASE_DEFAULT.copy()
    st.session_state.pop("w_trase_editor", None)
    _S()["trase_df"] = TRASE_DEFAULT.copy()


def halaman_trase():
    judul_halaman("Jarak, Azimut & Stasioning", "Dari koordinat trase menjadi jarak, sudut belok, dan STA yang konsisten.")
    st.write(
        "Masukkan koordinat titik **A (awal)**, **PI**, dan **B (akhir)**. Aplikasi menghitung jarak, azimut, sudut belok, "
        "tikungan pada tiap PI, lalu **STA TS, PI, dan ST** secara berantai."
    )
    c1, c2 = st.columns([1, 2])
    in_num("STA awal trase (m)", "sta_awal", 0.0, 10_000_000.0, 100.0, "%.3f", container=c1,
           help="Contoh: 0 untuk 0+000, 1000 untuk 1+000.")
    c2.markdown("Baris pertama = **A**, baris terakhir = **B**, baris di tengah = **PI-1, PI-2, …**. "
                "Kolom R, Vr, Jenis, dan Ls hanya dipakai pada baris PI. Tambah baris dengan menekan baris kosong paling bawah.")
    if "trase_base" not in st.session_state:
        st.session_state["trase_base"] = trase_df()
    st.button("Muat data contoh", on_click=_muat_contoh)
    edit = st.data_editor(
        st.session_state["trase_base"], key="w_trase_editor", num_rows="dynamic", use_container_width=True,
        column_config={
            "X": st.column_config.NumberColumn("X / Easting (m)", format="%.3f"),
            "Y": st.column_config.NumberColumn("Y / Northing (m)", format="%.3f"),
            "R": st.column_config.NumberColumn("R rencana (m)", min_value=0.0, format="%.2f"),
            "Vr": st.column_config.NumberColumn("Vr (km/jam)", min_value=0.0, format="%.0f"),
            "Jenis": st.column_config.SelectboxColumn("Jenis tikungan", options=["Otomatis", "FC", "SCS", "SS"]),
            "Ls": st.column_config.NumberColumn("Ls rencana SCS (0 = otomatis)", min_value=0.0, format="%.2f"),
        },
    )
    _S()["trase_df"] = edit
    tr = trase_hasil()
    if len(tr["titik"]) < 2:
        st.info("Isi minimal dua titik (A dan B).")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Jumlah titik PI", len(tr["pi"]))
    m2.metric("Panjang trase", f"{tr['panjang']:,.2f} m")
    m3.metric("STA awal", fmt_sta(V("sta_awal")))
    m4.metric("STA akhir", fmt_sta(tr["sta_akhir"]))

    st.subheader("1. Jarak dan azimut tiap ruas")
    st.dataframe(pd.DataFrame([
        {"Ruas": f"{r['dari']} → {r['ke']}", "ΔX (m)": f"{r['dx']:.3f}", "ΔY (m)": f"{r['dy']:.3f}",
         "Jarak (m)": f"{r['d']:.3f}", "Azimut (°)": f"{r['az']:.4f}", "Azimut (DMS)": dms(r["az"]),
         "Sisa jarak lurus (m)": f"{r['bebas']:.2f}"} for r in tr["ruas"]
    ]), hide_index=True, use_container_width=True)
    st.caption("Sisa jarak lurus = jarak ruas − Ts tikungan di kedua ujungnya. Jika negatif, kedua tikungan saling tumpang tindih.")

    if tr["pi"]:
        st.subheader("2. Sudut belok, tikungan, dan stasioning tiap PI")
        st.dataframe(pd.DataFrame([
            {"PI": p["nama"], "Δ (°)": f"{p['delta']:.4f}", "Arah": p["arah"], "Jenis": p["jenis"],
             "R (m)": f"{p['R']:.2f}" if not p["lurus"] else "-", "Vr": f"{p['Vr']:.0f}" if not p["lurus"] else "-",
             "Ts (m)": f"{p['Ts']:.3f}", "Ltot (m)": f"{p['Ltot']:.3f}",
             "STA TS": fmt_sta(p["sta_ts"]), "STA PI": fmt_sta(p["sta_pi"]), "STA ST": fmt_sta(p["sta_st"])}
            for p in tr["pi"]
        ]), hide_index=True, use_container_width=True)
    for w in tr["peringatan"]:
        st.warning(w)
    if not tr["peringatan"] and tr["pi"]:
        st.success("Tidak ada tangen yang tumpang tindih dan syarat tikungan terpenuhi.")

    st.subheader("3. Gambar trase")
    st.image(trase_png(tr), use_container_width=True)
    with st.expander("Tabel stasioning lengkap"):
        st.dataframe(pd.DataFrame([(n, fmt_sta(s), f"{s:.3f}") for n, s in tr["tabel_sta"]],
                                  columns=["Titik", "STA", "STA (m)"]), hide_index=True, use_container_width=True)
    st.info("Langkah berikutnya: buka **Tikungan** dan pilih *Ambil dari trase* untuk melihat rincian hitungan satu PI.")


# =============================================================================
#  HALAMAN 4 : HITUNG TIKUNGAN
# =============================================================================
def tampil_hasil(A):
    P, hasil, terpilih = A["P"], A["hasil"], A["terpilih"]
    dasar = A["dasar"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("f (koef. gesek)", f"{dasar['f']:.3f}")
    c2.metric("Rmin", f"{dasar['Rmin']:.2f} m", "Rc memenuhi" if dasar["R_ok"] else "Rc < Rmin",
              delta_color="normal" if dasar["R_ok"] else "inverse")
    c3.metric("Rekomendasi", label_pendek(A["saran"]))
    c4.metric("Dipakai", label_pendek(terpilih))

    h = hasil[terpilih]
    v = h["v"]
    st.subheader(f"Ringkasan tikungan {label_pendek(terpilih)}")
    kiri, kanan = st.columns([3, 2])
    with kiri:
        if terpilih == "FC":
            ks = [("Tc", v["Tc"]), ("Ec", v["Ec"]), ("Lc", v["Lc"]), ("Δ", v["delta"])]
        elif terpilih == "SCS":
            ks = [("Ts", v["Ts"]), ("Es", v["Es"]), ("Ls", v["Ls"]), ("Lc", v["Lc"]), ("θs", v["ths"]), ("θc", v["thc"])]
        else:
            ks = [("Ts", v["Ts"]), ("Es", v["Es"]), ("Ls", v["Ls"]), ("θs", v["ths"])]
        cols = st.columns(len(ks))
        for c, (n_, x) in zip(cols, ks):
            c.metric(n_, f"{x:.3f}")
        st.dataframe(pd.DataFrame([(n_, fmt_sta(s_)) for n_, s_ in h["sta"]], columns=["Titik", "STA"]),
                     hide_index=True, use_container_width=True)
        for ps in h["pesan"]:
            st.warning(ps)
    with kanan:
        st.image(skema_png(terpilih), caption=f"Skema {label_pendek(terpilih)} (ilustrasi)", use_container_width=True)

    st.subheader("Perhitungan lengkap per jenis tikungan")
    nama_lengkap = {"FC": "Full Circle (FC)", "SCS": "Spiral-Circle-Spiral (SCS)", "SS": "Spiral-Spiral (SS)"}
    for tp in ("FC", "SCS", "SS"):
        hh = hasil[tp]
        with st.expander(f"{nama_lengkap[tp]} ({'memenuhi' if hh['ok'] else 'perlu diperiksa'}){', dipakai' if tp == terpilih else ''}",
                         expanded=(tp == terpilih)):
            for ps in hh["pesan"]:
                st.warning(ps)
            if not hh["pesan"]:
                st.success("Semua syarat terpenuhi.")
            st.dataframe(df_hasil(hh["rows"], teks=True), use_container_width=True, hide_index=True)


def halaman_tikungan():
    judul_halaman("Hitung Tikungan", "Bandingkan Full Circle, Spiral-Circle-Spiral, dan Spiral-Spiral berdampingan.")
    tr = trase_hasil()
    pis = [p["nama"] for p in tr["pi"] if not p["lurus"]]
    opsi = ["Input manual"] + (["Ambil dari trase"] if pis else [])
    sumber = in_sel("Sumber data", "sumber", opsi, radio=True,
                    help="Ambil dari trase: Δ, R, Vr, dan STA PI diambil otomatis dari menu Jarak, Azimut & STA.")
    if sumber == "Ambil dari trase":
        pilih = in_sel("Pilih PI", "pi_pilih", pis)
        pi = next(p for p in tr["pi"] if p["nama"] == pilih)
        a, b, c, d, e = st.columns(5)
        a.metric("Δ", f"{pi['delta']:.4f}°")
        b.metric("Arah", pi["arah"])
        c.metric("R", f"{pi['R']:g} m")
        d.metric("Vr", f"{pi['Vr']:g} km/jam")
        e.metric("STA PI", fmt_sta(pi["sta_pi"]))
        st.caption("Ubah R, Vr, atau jenis tikungan di menu Trase & STA.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        in_num("Vr (km/jam)", "Vr", 20.0, 120.0, 5.0, "%.0f", container=c1)
        in_num("Radius Rc (m)", "Rc", 10.0, 5000.0, 10.0, "%.2f", container=c2)
        in_num("Sudut belok Δ (°)", "delta", 0.1, 179.0, 0.1, "%.4f", container=c3)
        in_num("STA PI (m)", "sta_pi", 0.0, 10_000_000.0, 5.0, "%.3f", container=c4,
               help="Ambil dari menu Jarak, Azimut & STA agar tidak menebak.")
        in_sel("Jenis tikungan", "jenis", ["Otomatis (rekomendasi)", "FC", "SCS", "SS"], container=c5)
    c1, c2 = st.columns(2)
    in_num("Superelevasi maksimum e maks (%)", "emax", 4.0, 12.0, 0.5, "%.1f", container=c1)
    with st.expander("Parameter lanjutan lengkung peralihan"):
        d1, d2, d3_ = st.columns(3)
        in_num("e normal (%)", "en", 0.0, 6.0, 0.5, "%.1f", container=d1)
        in_num("C (m/det³)", "Cc", 0.1, 2.0, 0.1, "%.2f", container=d2)
        in_num("C kriteria 1 (Shortt)", "C1", 0.1, 5.0, 0.1, "%.2f", container=d3_,
               help="Angka laporan setara C = 1.")
        d4, d5, d6 = st.columns(3)
        in_num("T waktu tempuh (detik)", "T", 1.0, 6.0, 0.5, "%.1f", container=d4)
        in_num("re landai relatif (0 = otomatis)", "re", 0.0, 0.1, 0.005, "%.3f", container=d5)
        if sumber == "Input manual":
            in_num("Ls rencana SCS (m, 0 = otomatis)", "Ls_rencana", 0.0, 500.0, 5.0, "%.2f", container=d6)
    st.divider()
    A = tikungan_aktif()
    tampil_hasil(A)
    tampil_superelevasi(A)


# =============================================================================
#  HALAMAN 5 : PELEBARAN
# =============================================================================
def halaman_pelebaran():
    judul_halaman("Pelebaran Perkerasan", "Kebutuhan pelebaran lajur di tikungan menurut kendaraan rencana.")
    A = tikungan_aktif()
    P = A["P"]
    st.caption(f"R = {P['Rc']:g} m dan Vr = {P['Vr']:g} km/jam mengikuti menu Tikungan.")
    c = st.columns(4)
    in_num("p – jarak gandar (m)", "p", 0.1, 20.0, 0.1, "%.2f", container=c[0])
    in_num("A – tonjolan depan (m)", "A", 0.0, 10.0, 0.1, "%.2f", container=c[1])
    in_num("b – lebar kendaraan (m)", "b", 1.0, 4.0, 0.1, "%.2f", container=c[2])
    in_num("n – jumlah lajur", "n", 1, 6, 1, container=c[3])
    c = st.columns(3)
    in_num("Bn – lebar perkerasan normal (m)", "Bn", 3.0, 30.0, 0.1, "%.2f", container=c[0])
    in_num("Koefisien Z", "kz", 0.05, 0.2, 0.005, "%.3f", container=c[1], help="Laporan: 0,1. Buku Bina Marga: 0,105.")
    in_chk("Pakai (n+1)·Td seperti laporan", "tdn", help="Jika tidak dicentang dipakai (n−1)·Td.", container=c[2])
    A = tikungan_aktif()
    P, pel = A["P"], A["peleb"]
    if P["Rc"] <= P["p"]:
        st.error("Radius harus lebih besar dari jarak gandar p.")
        return
    m1, m2, m3 = st.columns(3)
    m1.metric("Lebar di tikungan Bt", f"{pel['Bt']:.4f} m")
    m2.metric("Pelebaran total Δb", f"{pel['db_raw']:.4f} m")
    m3.metric("Per sisi", f"{pel['db_raw'] / 2:.4f} m")
    if pel["db_raw"] <= 0:
        st.info("Δb ≤ 0 → tidak diperlukan pelebaran.")
    st.dataframe(df_hasil(pel["rows"], teks=True), hide_index=True, use_container_width=True)
    st.subheader("Pengaruh radius terhadap pelebaran")
    data = []
    for R in range(int(P["p"]) + 5, 801, 10):
        data.append((R, aman_peleb(P, float(R), P["Vr"])["db_raw"]))
    st.line_chart(pd.DataFrame(data, columns=["R (m)", "Δb (m)"]).set_index("R (m)"))
    st.caption("Semakin kecil radius, semakin besar pelebaran yang dibutuhkan.")


# =============================================================================
#  HALAMAN 6 : JARAK PANDANG
# =============================================================================
def halaman_jarak_pandang():
    judul_halaman("Jarak Pandang", "Jarak pandang henti (JPH) dan mendahului (JPM) dibandingkan dengan standar.")
    A = tikungan_aktif()
    vr = A["P"]["Vr"]
    st.caption(f"Vr = {vr:g} km/jam mengikuti menu Tikungan.")
    c = st.columns(5)
    in_num("t – waktu reaksi (detik)", "t_r", 1.0, 4.0, 0.1, "%.1f", container=c[0])
    in_num("a – perlambatan (m/det²)", "a_dec", 1.0, 6.0, 0.1, "%.1f", container=c[1])
    in_num("G – kelandaian (%)", "G", -15.0, 15.0, 0.5, "%.1f", container=c[2], help="+ tanjakan, − turunan")
    in_num("m – selisih kecepatan (km/jam)", "m_sel", 5.0, 20.0, 1.0, "%.0f", container=c[3])
    in_num("d₃ – jarak bebas (m)", "d3", 30.0, 100.0, 5.0, "%.0f", container=c[4])
    G = V("G") / 100
    jph = hitung_jph(vr, V("t_r"), V("a_dec"), G)
    jpm = hitung_jpm(vr, V("m_sel"), V("d3"))
    jph_std, jpm_std = _nearest(JPH_STD, vr), _nearest(JPM_STD, vr)
    m1, m2 = st.columns(2)
    m1.metric("JPH", f"{jph[0]:.2f} m", f"standar min. {jph_std} m", delta_color="off")
    m2.metric("JPM", f"{jpm['JPM']:.2f} m", f"standar min. {jpm_std} m", delta_color="off")
    if jph[0] < jph_std:
        st.warning("JPH hitungan di bawah standar minimum.")
    if jpm["JPM"] < jpm_std:
        st.warning("JPM hitungan di bawah standar minimum.")
    t1, t2 = st.tabs(["JPH", "JPM"])
    with t1:
        st.dataframe(df_hasil([
            baris("Jarak reaksi", "d₁", "Vr·t / 3,6", jph[1], "m"),
            baris("Jarak pengereman", "d₂", "Vr² / [2·3,6²·9,81·(a/9,81 + G)]", jph[2], "m"),
            baris("Jarak pandang henti", "JPH", "d₁ + d₂", jph[0], "m"),
        ], teks=True), hide_index=True, use_container_width=True)
    with t2:
        st.dataframe(df_hasil([
            baris("Waktu penyesuaian awal", "T₁", "2,12 + 0,026·Vr", jpm["T1"], "detik"),
            baris("Waktu di lajur lawan", "T₂", "6,56 + 0,048·Vr", jpm["T2"], "detik"),
            baris("Percepatan rata-rata", "a", "2,052 + 0,0036·Vr", jpm["a"], "km/jam/detik"),
            baris("Jarak selama waktu tanggap", "d₁", "0,278·T₁·(Vr − m + a·T₁/2)", jpm["d1"], "m"),
            baris("Jarak selama mendahului", "d₂", "0,278·Vr·T₂", jpm["d2"], "m"),
            baris("Jarak bebas", "d₃", "input", jpm["d3"], "m"),
            baris("Jarak kendaraan lawan", "d₄", "2/3·d₂", jpm["d4"], "m"),
            baris("Jarak pandang mendahului", "JPM", "d₁ + d₂ + d₃ + d₄", jpm["JPM"], "m"),
        ], teks=True), hide_index=True, use_container_width=True)
    st.subheader("JPH menurut kecepatan rencana")
    kec = sorted(JPH_STD)
    st.bar_chart(pd.DataFrame({"Vr (km/jam)": [str(k) for k in kec],
                               "JPH hitungan (m)": [hitung_jph(k, V("t_r"), V("a_dec"), G)[0] for k in kec],
                               "JPH standar (m)": [JPH_STD[k] for k in kec]}).set_index("Vr (km/jam)"))


# =============================================================================
#  HALAMAN 7 : GAMBAR CAD & EXCEL
# =============================================================================
def _item(nama, h, P, arah="-", supe=None):
    return dict(h=h, P=P, peleb=aman_peleb(P, P["Rc"], P["Vr"]), judul=f"{nama} - {label_pendek(h['tipe'])}", arah=arah, supe=supe)


def halaman_output():
    judul_halaman("Gambar CAD & Excel", "Pratinjau gambar lalu unduh file .dxf untuk AutoCAD dan .xlsx berumus.")
    tr = trase_hasil()
    pis_ok = [p for p in tr["pi"] if not p["lurus"]]
    opsi = ["Tikungan aktif (menu Tikungan)"] + (["Seluruh tikungan pada trase"] if pis_ok else [])
    mode = in_sel("Yang digambar", "mode_out", opsi, radio=True)
    in_chk("Sertakan diagram superelevasi (satu lembar tambahan per tikungan)", "supe_dxf")
    A = tikungan_aktif()
    items = []
    dgn_supe = V("supe_dxf")
    manual = V("e_mode") == "Input manual"
    if mode.startswith("Tikungan aktif"):
        semua = in_chk("Gambar FC, SCS, dan SS sekaligus (satu lembar per jenis)", "semua")
        nama = A["info"]["nama"] if A["info"] else "TIKUNGAN"
        arah = A["info"]["arah"] if A["info"] else "-"
        jenis_list = ["FC", "SCS", "SS"] if semua else [A["terpilih"]]
        for t in jenis_list:
            if t == "SCS" and A["hasil"]["SCS"]["v"]["thc"] <= 0:
                st.warning("SCS tidak dapat digambar karena θc ≤ 0, dilewati.")
                continue
            sp_ = hitung_superelevasi(A["hasil"][t], A["P"], V("e_manual") / 100 if manual else 0.0, V("p_tan"), V("Ls_fc")) if dgn_supe else None
            items.append(_item(nama, A["hasil"][t], A["P"], arah, sp_))
    else:
        for p in pis_ok:
            if p["jenis"] == "SCS" and p["h"]["v"]["thc"] <= 0:
                st.warning(f"{p['nama']}: SCS tidak valid (θc ≤ 0), tidak digambar.")
                continue
            sp_ = hitung_superelevasi(p["h"], p["P"], 0.0, V("p_tan"), 0.0) if dgn_supe else None
            items.append(_item(p["nama"], p["h"], p["P"], p["arah"], sp_))

    st.subheader("Pratinjau gambar")
    dxf_bytes, doc = None, None
    if items:
        dxf_bytes, doc = buat_dxf(items)
        try:
            st.image(pratinjau_png(doc), caption="Pratinjau (isi file .dxf yang sama)", use_container_width=True)
        except Exception as e:
            st.info(f"Pratinjau tidak tersedia ({e}). File DXF tetap bisa diunduh dan dibuka di AutoCAD.")
        st.caption(f"{len(items) + sum(1 for i_ in items if i_.get('supe'))} lembar A3 berjajar ke kanan (denah tikungan, lalu diagram superelevasi bila dipilih). Satuan lembar: mm, skala tertera di tiap lembar.")
    else:
        st.error("Tidak ada tikungan yang bisa digambar.")

    # Excel
    base = trase_hasil()
    rows = baris_trase(trase_df())
    for i, p in enumerate(base["pi"], start=1):
        if i < len(rows) - 1:
            rows[i]["jenis_excel"] = p["jenis"] if p["jenis"] in ("FC", "SCS", "SS") else "FC"
    jp = dict(t_r=V("t_r"), a_dec=V("a_dec"), G=V("G") / 100, m_sel=V("m_sel"), d3=V("d3"),
              jph_std=_nearest(JPH_STD, A["P"]["Vr"]), jpm_std=_nearest(JPM_STD, A["P"]["Vr"]))
    xlsx = buat_excel(A["P"], A["sta_pi"], A["terpilih"], jp, rows, V("sta_awal"), supe_aktif(A)) if len(rows) >= 2 else None

    st.divider()
    d1, d2 = st.columns(2)
    if xlsx:
        d1.download_button("Unduh Excel (.xlsx)", xlsx, file_name="GeoJalan_Hitungan.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    if dxf_bytes:
        d2.download_button("Unduh gambar CAD (.dxf)", dxf_bytes, file_name="GeoJalan_Gambar.dxf",
                           mime="application/dxf", use_container_width=True)
    st.info(
        "**Isi Excel:** sheet *Parameter* (FC, SCS, SS), *Superelevasi*, *Pelebaran*, *Jarak Pandang*, dan *Trase & STA*. "
        "Sel biru berlatar kuning = input yang boleh diubah; sel lain berisi rumus Excel yang menghitung otomatis."
    )


# =============================================================================
#  MAIN
# =============================================================================
def superelevasi_png(sp):
    """Pratinjau diagram superelevasi + potongan melintang A-D (PNG resolusi tinggi)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    e, en = sp["e"] * 100, sp["en"] * 100
    xa, xb, L = sp["xa1"], sp["xb2"], sp["L"]
    ext = 0.35 * L
    fig = plt.figure(figsize=(10.5, 6.6), dpi=200)
    fig.patch.set_facecolor(_KERTAS)
    gs = fig.add_gridspec(2, 4, height_ratios=[2.2, 1], hspace=0.42, wspace=0.25)
    ax = fig.add_subplot(gs[0, :])
    ax.set_facecolor(_KERTAS)
    xs = [xa - ext] + [v[0] for v in sp["verts"]] + [xb + ext]
    ou = [-en] + [v[1] for v in sp["verts"]] + [-en]
    inn = [-en] + [v[2] for v in sp["verts"]] + [-en]
    ax.fill_between(xs, inn, ou, color=_KUN, alpha=0.16, lw=0)
    ax.plot(xs, ou, color="#C8372D", lw=2.6, label="Tepi luar", solid_joinstyle="miter")
    ax.plot(xs, inn, color="#1F5FBF", lw=2.6, label="Tepi dalam", solid_joinstyle="miter")
    ax.axhline(0, color=_INK, lw=1.0)
    for nm, x, sta in sp["titik"]:
        ax.axvline(x, color="#98A3AD", lw=0.9, ls=(0, (5, 4)))
        ax.text(x, e * 1.55 + 0.8, nm, ha="center", va="bottom", fontsize=9, fontweight="bold", color=_INK)
        ax.text(x, -e * 1.18 - 0.4, f"STA {fmt_sta(sta)}", ha="center", va="top", fontsize=6.8, color=_INK2, rotation=90)
    for kc in sp["kunci"]:
        ax.plot(kc["x"], kc["outer"], "o", color=_KERTAS, mec=_INK, mew=1.3, ms=6, zorder=5)
        ax.annotate(kc["huruf"], (kc["x"], kc["outer"]), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9, fontweight="bold", color=_INK)
    niv = sorted({round(v, 4) for v in (e, en, 0.0, -en, -e)})
    ax.set_yticks(niv)
    ax.set_yticklabels([f"{v:+.2f}%" if v else "0%" for v in niv], fontsize=8, color=_INK2)
    ax.set_ylim(-e * 1.9 - 1.5, e * 2.0 + 2.0)
    ax.set_xlim(xa - ext, xb + ext)
    ax.tick_params(axis="x", colors=_INK2, labelsize=8)
    ax.set_xlabel("Jarak dari TS / TC (m)", color=_INK2, fontsize=9)
    ax.grid(color="#DDE2E6", lw=0.6)
    for s_ in ax.spines.values():
        s_.set_color("#C3CBD2")
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.01), fontsize=8, frameon=False, ncol=2)
    for i, kc in enumerate(sp["kunci"]):
        a2 = fig.add_subplot(gs[1, i])
        a2.set_facecolor(_KERTAS)
        a2.plot([-1, 0, 1], [kc["inner"], 0, kc["outer"]], color=_ASP, lw=3.2, solid_joinstyle="miter")
        a2.plot([-1, 1], [0, 0], color="#98A3AD", lw=0.8, ls=(0, (4, 3)))
        a2.plot(-1, kc["inner"], "o", color="#1F5FBF", ms=5)
        a2.plot(1, kc["outer"], "o", color="#C8372D", ms=5)
        a2.text(-1, kc["inner"] - 2.6 - 0.0, fp(kc['inner']), ha="center", fontsize=7.5, color=_INK)
        a2.text(1, kc["outer"] + 0.9, fp(kc['outer']), ha="center", fontsize=7.5, color=_INK)
        a2.set_ylim(-e * 1.5 - 1, e * 1.5 + 2)
        a2.set_xlim(-1.35, 1.35)
        a2.axis("off")
        a2.set_title(f"Potongan {kc['huruf']}: {kc['ket']}\nSTA {fmt_sta(kc['sta'])}", fontsize=8, color=_INK, pad=2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=_KERTAS)
    plt.close(fig)
    return buf.getvalue()


def supe_aktif(A):
    h = A["hasil"][A["terpilih"]]
    manual = V("e_mode") == "Input manual"
    return hitung_superelevasi(h, A["P"], V("e_manual") / 100 if manual else 0.0, V("p_tan"), V("Ls_fc"))


def tampil_superelevasi(A):
    html('<div class="h-sec">Diagram superelevasi</div><p class="p-sec">Pencapaian kemiringan tepi luar dan tepi dalam jalan sepanjang tikungan, memutar terhadap as jalan. Ikut masuk ke file DXF dan Excel.</p>')
    c1, c2, c3 = st.columns(3)
    in_sel("Superelevasi rencana", "e_mode", ["Otomatis (rumus Bina Marga)", "Input manual"], radio=True, container=c1)
    if V("e_mode") == "Input manual":
        in_num("e rencana (%)", "e_manual", 0.5, 12.0, 0.1, "%.2f", container=c2)
    if A["terpilih"] == "FC":
        in_num("Porsi Ls' pada bagian lurus", "p_tan", 0.5, 1.0, 0.05, "%.2f", container=c2 if V("e_mode") != "Input manual" else c3,
               help="Umumnya 3/4 (0,75) di bagian lurus dan sisanya di busur. Sesuaikan dengan pedoman Anda.")
        in_num("Ls' fiktif FC (m, 0 = otomatis)", "Ls_fc", 0.0, 500.0, 5.0, "%.2f", container=c3)
    sp = supe_aktif(A)
    m = st.columns(4)
    m[0].metric("e rencana", f"{sp['e'] * 100:.2f}%")
    m[1].metric("e normal", f"{sp['en'] * 100:.2f}%")
    m[2].metric("Ls" if sp["tipe"] != "FC" else "Ls' (fiktif)", f"{sp['L']:.2f} m")
    m[3].metric("Perubahan kemiringan", f"{sp['re_akt']:.4f}", f"maks {sp['re_maks']:.3f}", delta_color="off")
    for ps in sp["pesan"]:
        st.warning(ps)
    st.image(superelevasi_png(sp), use_container_width=True)
    st.dataframe(pd.DataFrame([
        {"Potongan": kc["huruf"], "Keterangan": kc["ket"], "STA": fmt_sta(kc["sta"]),
         "Tepi luar": fp(kc['outer']), "Tepi dalam": fp(kc['inner'])} for kc in sp["kunci"]
    ]), hide_index=True, use_container_width=True)
    with st.expander("Cara perhitungan"):
        st.latex(r"e = -\frac{e_{maks}\,D^2}{D_{maks}^2} + \frac{2\,e_{maks}\,D}{D_{maks}}\qquad D = \frac{1432{,}4}{R}\qquad D_{maks} = \frac{181913{,}53\,(e_{maks}+f)}{V_r^2}")
        st.write("Tepi luar naik linier dari −en sampai +e. Tepi dalam tetap −en sampai tepi luar mencapai +en, lalu turun sampai −e. "
                 "Pada SCS dan SS pencapaian dilakukan sepanjang Ls. Pada FC dipakai Ls' fiktif, dengan sebagian di bagian lurus sebelum TC dan sisanya di busur.")


def judul_halaman(judul, ket=""):
    html(f'<div class="ph"><div class="ph-t">{judul}</div><div class="ph-d">{ket}</div></div>')


def _ke(halaman):
    st.session_state["menu"] = halaman


def _footer(lengkap=True):
    if not lengkap:
        html('<div class="ft-min">GeoJalan. Alat bantu hitung alinyemen horizontal. Periksa hasil terhadap pedoman proyek Anda sebelum dipakai untuk desain.</div>')
        return
    html(f"""
<div class="ft">
<div><div class="ft-b">{APP_NAMA}</div><p>Kalkulator geometri jalan untuk perencanaan alinyemen horizontal: tikungan, STA, pelebaran, jarak pandang, dan gambar CAD.</p></div>
<div><div class="ft-h">Rujukan</div><p>Bina Marga, TPGJAK No. 038/TBM/1997<br>Bina Marga, Pedoman Desain Geometrik Jalan (2021)<br>Sukirman, S. (1999), Dasar-Dasar Perencanaan Geometrik Jalan</p></div>
<div><div class="ft-h">Perlu diperhatikan</div><p>Ini alat bantu hitung. Cocokkan nilai standar (R minimum, e maks, jarak pandang) dengan pedoman yang dipakai proyek Anda sebelum dipakai untuk desain.</p></div>
</div>""")


# =============================================================================
#  BERANDA
# =============================================================================
def halaman_beranda():
    kiri, kanan = st.columns([5, 7], gap="large")
    with kiri:
        html('<div class="h-hero">Hitung tikungan, STA, dan gambar CAD dari koordinat trase.</div>')
        html('<p class="p-hero">Isi koordinat titik awal, PI, dan titik akhir. GeoJalan menghitung jarak, azimut, sudut belok, tikungan FC, SCS, atau SS, pelebaran, dan jarak pandang, lalu menyiapkan Excel berumus dan gambar DXF untuk AutoCAD.</p>')
        b1, b2 = st.columns(2)
        b1.button("Isi koordinat trase", on_click=_ke, args=(PAGES[2],), type="primary", use_container_width=True)
        b2.button("Baca materi dasar", on_click=_ke, args=(PAGES[1],), use_container_width=True)
        html('<p class="p-note">Dibuat untuk mahasiswa teknik sipil dan perencana jalan. Rumus mengikuti Bina Marga.</p>')
    with kanan:
        html('<div class="plan">' + picture(svg_plan(False), svg_plan(True), "Denah tikungan spiral-lingkaran-spiral dengan patok STA dan dimensi") + '</div>')

    html('<div class="h-sec">Hasil yang Anda dapatkan</div><p class="p-sec">Tiga keluaran dari satu kali isi data. Contoh di bawah dihitung dengan rumus yang sama seperti di aplikasi.</p>')
    t1, t2, t3 = st.tabs(["Gambar DXF", "Excel berumus", "Tabel STA"])
    with t1:
        html('<div class="sheet">' + picture(svg_lembar(), None, "Lembar A3 hasil ekspor DXF: skema tikungan, dimensi, dan tabel data") + '</div>')
        html('<p class="cap">Lembar A3 hasil ekspor: skema tikungan, tepi jalan dengan pelebaran, dimensi, dan tiga tabel data. Tanpa kop proyek, jadi bisa dipakai siapa saja. Satu lembar untuk tiap tikungan.</p>')
    with t2:
        html(excel_mock())
        html('<p class="cap">Empat sheet: Parameter (FC, SCS, SS), Pelebaran, Jarak Pandang, dan Trase &amp; STA. Ubah angka input dan seluruh hasil ikut berubah.</p>')
    with t3:
        html(sta_mock())

    html('<div class="h-sec">Alur kerja dan alasannya</div>')
    a, b = st.columns([5, 6], gap="large")
    with a:
        html("""
<div class="route">
<div class="rs" data-n="1"><b>Masukkan koordinat</b><span>Titik A, semua PI, dan titik B di menu Trase &amp; STA.</span></div>
<div class="rs" data-n="2"><b>Lihat jarak, azimut, dan Δ</b><span>Keluar otomatis, termasuk arah belok kiri atau kanan.</span></div>
<div class="rs" data-n="3"><b>Pilih jenis tikungan</b><span>FC, SCS, dan SS dihitung berdampingan di menu Tikungan, lengkap dengan rekomendasi.</span></div>
<div class="rs" data-n="4"><b>Periksa pelebaran dan jarak pandang</b><span>Menu Pelebaran dan Jarak Pandang memakai R dan Vr yang sama.</span></div>
<div class="rs" data-n="5"><b>Unduh hasil</b><span>Excel berumus dan gambar DXF di menu Gambar &amp; Excel.</span></div>
</div>""")
    with b:
        html("""
<table class="cmp"><tr><th></th><th>Hitung manual</th><th>Dengan GeoJalan</th></tr>
<tr><td>Jarak dan azimut</td><td>Kalkulator, ruas demi ruas</td><td>Otomatis dari koordinat</td></tr>
<tr><td>STA tiap PI</td><td>Rantai hitungan panjang, mudah keliru</td><td>Dihitung berantai, tangen tumpang tindih diberi peringatan</td></tr>
<tr><td>Ganti R atau Vr</td><td>Hitung dan gambar ulang semuanya</td><td>Semua tabel dan gambar ikut berubah</td></tr>
<tr><td>Pilih FC, SCS, atau SS</td><td>Hitung tiga kali</td><td>Tiga hasil sekaligus</td></tr>
<tr><td>Gambar di CAD</td><td>Digambar garis demi garis</td><td>File DXF jadi dengan dimensi</td></tr>
<tr><td>Memeriksa hitungan</td><td>Buka kertas hitungan</td><td>Rumus terlihat di setiap sel Excel</td></tr>
</table>""")

    html('<div class="h-sec">Yang dihitung</div>')
    html("""
<table class="spec">
<tr><th>Bagian</th><th>Isi</th><th>Menu</th></tr>
<tr><td>Trase</td><td>Jarak, azimut, sudut belok, dan arah belok tiap ruas. STA TS, PI, dan ST berantai untuk banyak PI. Gambar trase dengan patok STA.</td><td>Trase &amp; STA</td></tr>
<tr><td>Tikungan</td><td>Full Circle, Spiral-Circle-Spiral, dan Spiral-Spiral. Empat kriteria Ls minimum, syarat tiap jenis, dan rekomendasi.</td><td>Tikungan</td></tr>
<tr><td>Superelevasi</td><td>e rencana dengan rumus Bina Marga, diagram pencapaian tepi luar dan tepi dalam, serta potongan melintang A sampai D.</td><td>Tikungan</td></tr>
<tr><td>Pelebaran</td><td>Lebar perkerasan di tikungan dari data kendaraan rencana (p, A, b), jumlah lajur, dan lebar normal.</td><td>Pelebaran</td></tr>
<tr><td>Jarak pandang</td><td>JPH dan JPM, dibandingkan dengan nilai minimum standar.</td><td>Jarak Pandang</td></tr>
<tr><td>Excel</td><td>Empat sheet dengan rumus asli di sel hasil.</td><td>Gambar &amp; Excel</td></tr>
<tr><td>DXF</td><td>Lembar A3 per tikungan: skema, tepi jalan, dimensi, tabel data, dan diagram superelevasi.</td><td>Gambar &amp; Excel</td></tr>
</table>""")

    html('<div class="h-sec">Pertanyaan yang sering muncul</div>')
    with st.expander("Apakah hasilnya bisa langsung dipakai untuk desain?"):
        st.write("Ini alat bantu hitung. Rumusnya mengikuti rujukan Bina Marga, tetapi nilai standar seperti R minimum, e maksimum, dan jarak pandang minimum perlu dicocokkan dengan edisi pedoman yang dipakai proyek Anda.")
    with st.expander("Bagaimana STA dihitung?"):
        st.write("STA PI sebuah tikungan = STA ST tikungan sebelumnya + jarak antar-PI − Ts tikungan sebelumnya. Jadi STA bukan sekadar jumlah jarak PI ke PI. Rumus lengkap ada di menu Materi, tab Azimut, Jarak & STA.")
    with st.expander("Kenapa hasil SS bisa berbeda dari hitungan manual saya?"):
        st.write("Pada Spiral-Spiral, panjang spiral ditentukan geometri: Ls = θs·π·R/90 dengan θs = Δ/2. Jika hitungan manual memakai Ls yang dibulatkan atau dari rumus lain, hasilnya sedikit berbeda. Aplikasi memberi peringatan bila Ls di bawah Ls minimum.")
    with st.expander("Bisakah dipakai tanpa internet?"):
        st.write("Bisa. Jalankan di komputer sendiri memakai Jalankan_Windows.bat atau jalankan_mac_linux.sh. Internet hanya perlu saat pemasangan pertama. Lihat README.")
    with st.expander("Apakah file Excel boleh saya ubah?"):
        st.write("Boleh. Sel biru berlatar kuning adalah input. Sel lain berisi rumus Excel asli sehingga bisa diperiksa langkah demi langkah.")
    _footer(True)


# =============================================================================
#  TENTANG
# =============================================================================
def halaman_tentang():
    judul_halaman("Tentang GeoJalan", "Tujuan, batasan, dan rujukan aplikasi ini.")
    a, b = st.columns(2, gap="large")
    with a:
        html('<div class="h-sub">Tujuan</div>')
        st.write("Perencanaan alinyemen horizontal penuh hitungan berulang. GeoJalan dibuat supaya hitungan itu cepat, konsisten, dan bisa diperiksa: dari koordinat trase sampai tabel STA, Excel berumus, dan gambar DXF.")
        html('<div class="h-sub">Sudah tersedia</div>')
        st.markdown(
            "- Jarak, azimut, sudut belok, dan arah belok dari koordinat\n"
            "- Tikungan FC, SCS, dan SS dengan rekomendasi jenis\n"
            "- STA berantai untuk banyak PI dan peringatan tangen tumpang tindih\n"
            "- Pelebaran perkerasan dan jarak pandang (JPH, JPM)\n"
            "- Diagram superelevasi dengan potongan melintang, di DXF dan Excel\n"
            "- Excel dengan rumus asli dan gambar DXF per tikungan"
        )
    with b:
        html('<div class="h-sub">Belum tersedia</div>')
        st.markdown(
            "- Tikungan majemuk (gabungan dua busur)\n"
            "- Alinyemen vertikal serta galian dan timbunan\n"
            "- Gambar tikungan belok kanan sebagai cermin sebenarnya (skema digambar belok kiri, arah tertulis di tabel)"
        )
        html('<div class="h-sub">Versi</div>')
        st.write(f"{APP_NAMA} versi {APP_VERSI}.")
        if PEMBUAT:
            html('<div class="h-sub">Pembuat</div>')
            st.write(PEMBUAT)
    html('<div class="h-sub">Rujukan</div>')
    st.markdown(
        "- Direktorat Jenderal Bina Marga, *Tata Cara Perencanaan Geometrik Jalan Antar Kota* (TPGJAK), No. 038/TBM/1997.\n"
        "- Direktorat Jenderal Bina Marga, *Pedoman Desain Geometrik Jalan* (2021).\n"
        "- Sukirman, S. (1999). *Dasar-Dasar Perencanaan Geometrik Jalan*. Bandung: Nova."
    )
    st.info("Cocokkan nilai standar dengan edisi pedoman yang dipakai pada proyek Anda sebelum hasil dipakai untuk desain.")
    _footer(True)


# =============================================================================
#  MAIN
# =============================================================================
def main():
    st.set_page_config(page_title="GeoJalan – kalkulator geometri tikungan jalan", page_icon=favicon(), layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    html(f'<div class="top"><img class="top-logo" src="{svg_uri(LOGO_SVG)}" alt=""><div class="top-name">{APP_NAMA}</div>'
         '<div class="top-sub">Kalkulator geometri tikungan jalan</div></div>')
    if st.session_state.get("menu") not in PAGES:
        st.session_state["menu"] = PAGES[0]
    with st.container(key="nav"):
        for c, p in zip(st.columns(len(PAGES)), PAGES):
            c.button(p, key=f"nav_{p}", on_click=_ke, args=(p,), use_container_width=True,
                     type="primary" if st.session_state["menu"] == p else "secondary")
    page = st.session_state["menu"]
    if st.session_state.get("_prev_page") != page:
        st.session_state["_prev_page"] = page
        if page == PAGES[2]:
            st.session_state["trase_base"] = trase_df()
            st.session_state.pop("w_trase_editor", None)
    {
        PAGES[0]: halaman_beranda, PAGES[1]: halaman_materi, PAGES[2]: halaman_trase, PAGES[3]: halaman_tikungan,
        PAGES[4]: halaman_pelebaran, PAGES[5]: halaman_jarak_pandang, PAGES[6]: halaman_output, PAGES[7]: halaman_tentang,
    }[page]()
    if page not in (PAGES[0], PAGES[7]):
        _footer(False)


if __name__ == "__main__":
    main()
