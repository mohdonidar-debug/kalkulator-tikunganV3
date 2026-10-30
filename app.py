"""
KALKULATOR GEOMETRI TIKUNGAN JALAN  (FC - SCS - SS)
Streamlit + ezdxf + pandas/openpyxl

Jalankan :  streamlit run app.py
Install  :  pip install streamlit ezdxf pandas numpy openpyxl matplotlib
"""
import io
import math

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
        "SUMBU": (8, "CENTER"),
    }
    for nama, (warna, lt) in spesifikasi.items():
        doc.layers.add(nama, color=warna, linetype=lt)
    return doc


def _kotak(ks, x0, y0, x1, y1, layer="FRAME", **kw):
    ks.poli([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, close=True, **kw)


def _strip_bawah(ks, ox, judul, skala):
    """Strip tipis di bawah lembar: hanya nama tikungan dan skala (tanpa kop proyek)."""
    x0, x1 = ox + 10, ox + SHEET_W - 10
    _kotak(ks, x0, 10, x1, 24, lineweight=50)
    ks.garis((x1 - 60, 10), (x1 - 60, 24), "FRAME")
    ks.teks(judul.upper(), (x0 + 4, 17), 4.0, align="MIDDLE_LEFT")
    ks.teks(f"SKALA 1 : {skala}", (x1 - 30, 17), 3.5)


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


def buat_dxf(items):
    """items: list dict(h=hasil_tikungan, P=param, peleb=hasil_pelebaran, judul=str, arah=str).
    Satu lembar A3 per item, disusun berjajar ke kanan."""
    doc = _buat_doc()
    for i, it in enumerate(items):
        gambar_tikungan(doc, it, ox=i * (SHEET_W + 40))
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


def buat_excel(P, sta_pi, jenis, jp, trase_rows, sta_awal):
    """P : parameter tikungan aktif. trase_rows : baris trase (dengan kunci 'jenis_excel')."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Parameter"
    _sheet_parameter(ws, P, sta_pi, jenis)
    _sheet_pelebaran(wb.create_sheet("Pelebaran"), P)
    _sheet_jarak_pandang(wb.create_sheet("Jarak Pandang"), P, jp)
    _sheet_trase(wb.create_sheet("Trase & STA"), trase_rows, sta_awal, P)
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ===== UI =====================================================================
PAGES = [
    "🏠 Beranda",
    "📚 Materi Dasar",
    "📏 Jarak, Azimut & STA",
    "🔄 Hitung Tikungan",
    "↔️ Pelebaran Perkerasan",
    "👁️ Jarak Pandang",
    "📤 Gambar CAD & Excel",
]

NAV = {
    PAGES[0]: "🏠 Beranda", PAGES[1]: "📚 Materi", PAGES[2]: "📏 Trase & STA", PAGES[3]: "🔄 Tikungan",
    PAGES[4]: "↔️ Pelebaran", PAGES[5]: "👁️ Jarak Pandang", PAGES[6]: "📤 Gambar & Excel",
}

DEF = dict(
    Vr=80.0, Rc=240.0, delta=16.8, emax=8.0, sta_pi=385.0, jenis="Otomatis (rekomendasi)", sumber="Input manual",
    pi_pilih="PI-1", en=2.0, Cc=0.4, C1=1.0, T=3.0, re=0.0, Ls_rencana=0.0,
    p=7.6, A=2.1, b=2.6, n=2, Bn=7.0, kz=0.1, tdn=True,
    t_r=2.5, a_dec=3.4, G=0.0, m_sel=15.0, d3=100.0,
    sta_awal=0.0, semua=False, mode_out="Tikungan aktif (menu Hitung Tikungan)",
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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--brand:#0f766e;--brand2:#14b8a6;--navy:#0b2540;--line:rgba(148,163,184,.34);--card:rgba(148,163,184,.12);}
html,body,[class*="css"],.stApp{font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;}
h1,h2,h3,h4{letter-spacing:-.015em;font-weight:700;}
/* ---- buang elemen bawaan Streamlit agar terasa seperti website ---- */
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important;}
header[data-testid="stHeader"]{background:transparent;height:0;}
[data-testid="stSidebar"],[data-testid="collapsedControl"],[data-testid="stSidebarCollapsedControl"]{display:none!important;}
.block-container{max-width:1180px;padding-top:1.2rem;padding-bottom:3rem;}
/* ---- bilah navigasi atas ---- */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:.2rem .2rem .7rem .2rem;}
.brand{display:flex;align-items:center;gap:.7rem;}
.logo{width:2.5rem;height:2.5rem;border-radius:12px;background:linear-gradient(135deg,var(--brand),var(--brand2));display:flex;align-items:center;justify-content:center;font-size:1.3rem;box-shadow:0 6px 16px rgba(15,118,110,.35);}
.brand b{font-size:1.1rem;display:block;line-height:1.1;}
.brand small{opacity:.65;font-size:.78rem;}
.st-key-nav button{border-radius:12px;padding:.5rem .2rem;white-space:nowrap;}
.st-key-nav button p{font-size:.86rem;font-weight:600;}
/* ---- hero ---- */
.hero{position:relative;overflow:hidden;background:radial-gradient(1200px 400px at 85% -10%,rgba(20,184,166,.55),transparent 60%),linear-gradient(135deg,#0b2540 0%,#0f4c5c 55%,#0f766e 100%);padding:3rem 2.6rem 2.6rem 2.6rem;border-radius:24px;color:#fff;margin:.8rem 0 1.2rem 0;box-shadow:0 22px 50px rgba(11,37,64,.28);}
.hero:after{content:"";position:absolute;right:-60px;top:-60px;width:260px;height:260px;border-radius:50%;border:44px solid rgba(255,255,255,.07);}
.hero h1{margin:.5rem 0 .8rem 0;font-size:2.7rem;line-height:1.12;color:#fff;font-weight:800;max-width:46rem;}
.hero p{margin:0;font-size:1.08rem;opacity:.93;max-width:44rem;line-height:1.6;color:#e8f4f3;}
.tag{display:inline-block;padding:.22rem .8rem;border-radius:999px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);font-size:.78rem;font-weight:600;margin:0 .35rem .3rem 0;}
/* ---- statistik, kartu ---- */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:.9rem;margin:.4rem 0 1.4rem 0;}
.stat{background:var(--card);border:1px solid var(--line);border-top:3px solid #14b8a6;border-radius:16px;padding:1rem 1.1rem;box-shadow:0 6px 20px rgba(0,0,0,.10);}
.stat b{display:block;font-size:1.7rem;font-weight:800;background:linear-gradient(135deg,var(--brand),#0ea5e9);-webkit-background-clip:text;background-clip:text;color:transparent;}
.stat span{font-size:.85rem;opacity:.75;}
.kartu{border:1px solid var(--line);border-top:3px solid #14b8a6;border-radius:18px;padding:1.15rem 1.25rem;height:100%;background:var(--card);box-shadow:0 6px 20px rgba(0,0,0,.10);transition:transform .18s ease,box-shadow .18s ease;}
.kartu:hover{transform:translateY(-3px);box-shadow:0 14px 30px rgba(0,0,0,.22);}
.kartu .ik{width:2.6rem;height:2.6rem;border-radius:12px;background:linear-gradient(135deg,rgba(15,118,110,.14),rgba(14,165,233,.16));display:flex;align-items:center;justify-content:center;font-size:1.3rem;margin-bottom:.7rem;}
.kartu h4{margin:.1rem 0 .4rem 0;font-size:1.05rem;}
.kartu p,.kartu li{font-size:.92rem;line-height:1.55;opacity:.88;margin:0;}
.kartu ul{padding-left:1.1rem;margin:.2rem 0 0 0;}
.seksi{margin:2rem 0 .8rem 0;}
.seksi h3{margin:0;font-size:1.5rem;}
.seksi p{margin:.25rem 0 0 0;opacity:.7;}
.langkah{display:flex;gap:.9rem;align-items:flex-start;margin:.2rem 0;padding:.85rem 1rem;border:1px solid var(--line);border-radius:14px;background:var(--card);}
.no{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;border-radius:50%;min-width:2.1rem;height:2.1rem;display:flex;align-items:center;justify-content:center;font-weight:700;box-shadow:0 5px 12px rgba(15,118,110,.3);}
.langkah b{display:block;}
.langkah span{font-size:.9rem;opacity:.78;}
/* ---- header halaman ---- */
.phead{display:flex;align-items:center;gap:1rem;padding:1.3rem 1.5rem;border-radius:20px;margin:.8rem 0 1.2rem 0;color:#fff;background:linear-gradient(135deg,#0b2540,#0f766e);box-shadow:0 14px 34px rgba(11,37,64,.2);}
.phead .pico{font-size:1.9rem;width:3.4rem;height:3.4rem;border-radius:16px;background:rgba(255,255,255,.14);display:flex;align-items:center;justify-content:center;}
.phead h2{margin:0;font-size:1.6rem;color:#fff;font-weight:800;}
.phead p{margin:.2rem 0 0 0;opacity:.88;font-size:.95rem;color:#e8f4f3;}
/* ---- komponen streamlit ---- */
[data-testid="stMetric"]{background:var(--card);border:1px solid var(--line);padding:.85rem 1rem;border-radius:16px;box-shadow:0 5px 16px rgba(0,0,0,.10);}
[data-testid="stMetricLabel"] p{font-size:.8rem;opacity:.7;font-weight:600;}
[data-testid="stMetricValue"]{font-weight:800;}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:14px;overflow:hidden;}
[data-testid="stExpander"]{border:1px solid var(--line);border-radius:14px;background:var(--card);}
button[data-baseweb="tab"]{font-weight:600;}
.stButton>button,.stDownloadButton>button{border-radius:12px;font-weight:600;padding:.6rem 1.2rem;transition:all .15s ease;border:1px solid var(--line);}
.stButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-1px);box-shadow:0 8px 18px rgba(0,0,0,.22);}
.stButton>button[kind="primary"],.stDownloadButton>button{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;border:none;}
.stButton>button[kind="primary"] p,.stDownloadButton>button p{color:#fff;}
div[data-testid="stNumberInput"] input,div[data-baseweb="select"]>div{border-radius:10px;}
.foot{margin-top:2.6rem;padding:1.3rem 1.4rem;border-radius:18px;border:1px solid var(--line);background:var(--card);font-size:.85rem;opacity:.9;}
.foot b{font-size:.95rem;}
@media(max-width:800px){.stats{grid-template-columns:repeat(2,1fr);}.hero h1{font-size:2rem;}.hero{padding:2rem 1.4rem;}}
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
@st.cache_data(show_spinner=False)
def skema_png(tipe):
    """Skema contoh tikungan untuk halaman materi."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    base = dict(Vr=60.0, emax=.08, en=.02, Cc=.4, C1=1.0, T=3.0, re=0.0, p=7.6, A=2.1, b=2.6, n=2, Bn=7.0, kz=.1, td_n_plus_1=True)
    if tipe == "FC":
        P = dict(base, Rc=120.0, delta=50.0, Ls_rencana=0.0)
        h = hitung_fc(P, 0)
    elif tipe == "SCS":
        P = dict(base, Rc=100.0, delta=75.0, Ls_rencana=40.0)
        h = hitung_scs(P, 0)
    else:
        P = dict(base, Rc=100.0, delta=50.0, Ls_rencana=0.0)
        h = hitung_ss(P, 0)
    g = bangun_geometri(h, ext=35.0)
    fig, ax = plt.subplots(figsize=(5.4, 4.4), dpi=120)
    PI, O, ST = g["PI"], g["O"], g["ST"]
    ax.plot([-35, PI[0]], [0, 0], color="#444", lw=1.1)
    ax.plot([PI[0], ST[0] + 35 * g["dirB"][0]], [PI[1], ST[1] + 35 * g["dirB"][1]], color="#444", lw=1.1)
    ax.plot(g["curva"][:, 0], g["curva"][:, 1], color="#d62728", lw=2.8)
    ax.plot([PI[0], O[0]], [PI[1], O[1]], ls="-.", color="#888", lw=0.8)
    if tipe == "FC":
        marks = [("TC", g["TC"]), ("CT", g["CT"])]
    elif tipe == "SCS":
        marks = [("TS", g["TS"]), ("SC", g["SC"]), ("CS", g["CS"]), ("ST", g["ST"])]
    else:
        marks = [("TS", g["TS"]), ("SS", g["SC"]), ("ST", g["ST"])]
    for _, p in marks:
        ax.plot([O[0], p[0]], [O[1], p[1]], ls="--", color="#2ca02c", lw=0.8)
    for nm, p in marks + [("PI", PI), ("O", O)]:
        ax.plot(*p, "o", color="#1f4e78", ms=4)
        ax.annotate(nm, p, textcoords="offset points", xytext=(6, 5), fontsize=10, fontweight="bold")
    ax.set_aspect("equal")
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def plot_trase(tr):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5.2))
    xs = [t[1] for t in tr["titik"]]
    ys = [t[2] for t in tr["titik"]]
    ax.plot(xs, ys, "--", color="#888", lw=1, label="Garis PI (tangen)")
    pts = [np.array([xs[0], ys[0]])]
    for pi in tr["pi"]:
        if pi["lurus"] or (pi["jenis"] == "SCS" and pi["h"]["v"]["thc"] <= 0):
            pts.append(np.array(pi["xy"]))
        else:
            pts.extend(list(kurva_global(pi)))
    pts.append(np.array([xs[-1], ys[-1]]))
    arr = np.array(pts)
    ax.plot(arr[:, 0], arr[:, 1], color="#d62728", lw=2.2, label="As jalan (dengan lengkung)")
    for nama, x, y in tr["titik"]:
        ax.plot(x, y, "o", ms=5, color="#1f4e78")
        ax.annotate(nama, (x, y), textcoords="offset points", xytext=(6, 6), fontsize=9)
    ax.set_aspect("equal")
    ax.grid(alpha=.3)
    ax.set_xlabel("X / Easting (m)")
    ax.set_ylabel("Y / Northing (m)")
    ax.legend(loc="best")
    return fig


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
def judul_halaman(ikon, judul, ket=""):
    st.markdown(f'<div class="phead"><div class="pico">{ikon}</div><div><h2>{judul}</h2><p>{ket}</p></div></div>', unsafe_allow_html=True)


def _ke(halaman):
    st.session_state["menu"] = halaman


def halaman_beranda():
    st.markdown(
        """<div class="hero"><span class="tag">Gratis</span><span class="tag">Excel berumus</span><span class="tag">DXF untuk AutoCAD</span><span class="tag">Bisa offline</span>
<h1>Hitung tikungan jalan dari koordinat sampai gambar CAD, dalam hitungan menit.</h1>
<p>Masukkan koordinat trase, dan aplikasi menghitung jarak, azimut, sudut belok, tikungan FC / SCS / SS, pelebaran, jarak pandang, dan stasioning. Hasilnya langsung bisa diunduh sebagai Excel berumus dan gambar DXF.</p></div>""",
        unsafe_allow_html=True,
    )
    b1, b2, b3, _ = st.columns([1.3, 1.3, 1.3, 1])
    b1.button("Mulai hitung trase  →", on_click=_ke, args=(PAGES[2],), type="primary", use_container_width=True)
    b2.button("Hitung satu tikungan", on_click=_ke, args=(PAGES[3],), use_container_width=True)
    b3.button("Pelajari materinya", on_click=_ke, args=(PAGES[1],), use_container_width=True)

    st.markdown(
        """<div class="stats" style="margin-top:1.4rem">
<div class="stat"><b>3 jenis</b><span>tikungan FC, SCS, dan SS dihitung berdampingan</span></div>
<div class="stat"><b>4 sheet</b><span>Excel dengan rumus asli di setiap sel hasil</span></div>
<div class="stat"><b>A3 · DXF</b><span>gambar berdimensi, siap dibuka di AutoCAD</span></div>
<div class="stat"><b>Banyak PI</b><span>STA dihitung berantai dalam satu trase</span></div></div>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="seksi"><h3>Mengapa aplikasi ini dibuat?</h3><p>Perencanaan alinyemen horizontal itu berulang, dan satu angka yang berubah memaksa semuanya dikerjakan ulang.</p></div>', unsafe_allow_html=True)
    k1, k2 = st.columns(2)
    k1.markdown(
        """<div class="kartu"><div class="ik">😓</div><h4>Cara manual</h4><ul>
<li>Hitung jarak dan azimut tiap ruas dengan kalkulator</li>
<li>Rumus tikungan diketik ulang untuk setiap PI</li>
<li>STA sering ditebak karena rantai hitungannya panjang</li>
<li>R atau Vr berubah, semua dihitung dan digambar ulang di CAD</li></ul></div>""",
        unsafe_allow_html=True,
    )
    k2.markdown(
        """<div class="kartu"><div class="ik">🚀</div><h4>Dengan aplikasi ini</h4><ul>
<li>Isi koordinat sekali, jarak, azimut, dan Δ keluar otomatis</li>
<li>Rumus baku dan konsisten, syarat tikungan dicek otomatis</li>
<li>STA dihitung berantai dan tangen tumpang tindih diberi peringatan</li>
<li>Ubah satu angka, tabel, Excel, dan gambar DXF ikut berubah</li></ul></div>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="seksi"><h3>Yang bisa dilakukan</h3><p>Semua langkah alinyemen horizontal dalam satu tempat.</p></div>', unsafe_allow_html=True)
    fitur = [
        ("📏", "Trase & STA", "Jarak, azimut, sudut belok, arah belok, dan STA TS/PI/ST untuk banyak PI sekaligus, plus gambar trase."),
        ("🔄", "FC · SCS · SS", "Tiga jenis tikungan dengan rumus dan syarat, plus rekomendasi jenis yang cocok."),
        ("↔️", "Pelebaran perkerasan", "Hitung kebutuhan pelebaran dengan data kendaraan rencana yang bisa diubah."),
        ("👁️", "Jarak pandang", "JPH dan JPM dibandingkan dengan nilai minimum standar."),
        ("📊", "Excel berumus", "Sel hasil berisi rumus Excel, bukan teks. Ubah input, hasil ikut berubah."),
        ("📐", "Gambar DXF", "Skema tikungan, tepi jalan, dimensi, dan tabel data pada lembar A3."),
    ]
    for baris_ in (fitur[:3], fitur[3:]):
        cols = st.columns(3)
        for c, (ik, jd, ket) in zip(cols, baris_):
            c.markdown(f'<div class="kartu"><div class="ik">{ik}</div><h4>{jd}</h4><p>{ket}</p></div>', unsafe_allow_html=True)
        st.write("")

    st.markdown('<div class="seksi"><h3>Cara memakainya</h3><p>Lima langkah dari data lapangan sampai file siap pakai.</p></div>', unsafe_allow_html=True)
    langkah = [
        ("Pelajari dasarnya", "Menu Materi Dasar menjelaskan jenis tikungan, rumus, dan istilah."),
        ("Masukkan koordinat trase", "Menu Jarak, Azimut & STA: isi koordinat A, PI, dan B."),
        ("Hitung tikungan", "Menu Hitung Tikungan: ambil PI dari trase atau isi manual, lalu bandingkan FC, SCS, dan SS."),
        ("Cek pelebaran dan jarak pandang", "Menu Pelebaran Perkerasan dan Jarak Pandang."),
        ("Unduh hasil", "Menu Gambar CAD & Excel: pratinjau gambar, lalu unduh .dxf dan .xlsx."),
    ]
    for i, (jd, ket) in enumerate(langkah, start=1):
        st.markdown(f'<div class="langkah"><div class="no">{i}</div><div><b>{jd}</b><span>{ket}</span></div></div>', unsafe_allow_html=True)

    st.markdown('<div class="seksi"><h3>Pertanyaan yang sering muncul</h3></div>', unsafe_allow_html=True)
    with st.expander("Apakah hasilnya bisa dipakai langsung untuk desain?"):
        st.write("Aplikasi ini alat bantu hitung. Rumusnya mengikuti rujukan Bina Marga, tetapi nilai standar (R minimum, e maks, jarak pandang, dan lainnya) perlu dicocokkan dengan edisi pedoman yang dipakai pada proyek Anda sebelum dipakai untuk desain.")
    with st.expander("Bagaimana STA dihitung?"):
        st.write("STA PI sebuah tikungan = STA ST tikungan sebelumnya + jarak antar-PI − Ts tikungan sebelumnya. Jadi STA tidak sekadar jumlah jarak PI ke PI. Rumus lengkap ada di Materi Dasar, tab Azimut, Jarak & STA.")
    with st.expander("Kenapa hasil SS bisa berbeda dari hitungan manual saya?"):
        st.write("Pada tikungan Spiral-Spiral, panjang spiral ditentukan oleh geometri: Ls = θs·π·R/90 dengan θs = Δ/2. Jika hitungan manual memakai Ls yang dibulatkan atau dari rumus lain, hasilnya akan sedikit berbeda. Aplikasi memberi peringatan bila Ls di bawah Ls minimum.")
    with st.expander("Bisakah dipakai tanpa internet?"):
        st.write("Bisa. Jalankan aplikasi ini di komputer sendiri memakai file peluncur (Jalankan_Windows.bat atau jalankan_mac_linux.sh). Internet hanya dibutuhkan saat pemasangan pertama. Petunjuk lengkap ada di README.")
    with st.expander("Apakah file Excel bisa saya ubah?"):
        st.write("Bisa. Sel biru berlatar kuning adalah input. Sel lain berisi rumus Excel asli sehingga bisa diperiksa langkah demi langkah dan menghitung ulang otomatis.")

    st.markdown(
        """<div class="foot"><b>Catatan penting</b><br>Alat bantu hitung untuk perencanaan alinyemen horizontal. Periksa hasil terhadap pedoman yang berlaku (mis. Pedoman Desain Geometrik Jalan Bina Marga dan TPGJAK 1997) sebelum dipakai untuk desain.</div>""",
        unsafe_allow_html=True,
    )


# =============================================================================
#  HALAMAN 2 : MATERI DASAR
# =============================================================================
def halaman_materi():
    judul_halaman("📚", "Materi Dasar Alinyemen Horizontal", "Ringkasan teori yang dipakai di aplikasi ini. Rumusnya sama dengan menu hitung dan Excel.")
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
            "Catatan: aplikasi ini belum menggambar diagram superelevasi."
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
    judul_halaman("📏", "Jarak, Azimut & Stasioning", "Dari koordinat trase menjadi jarak, sudut belok, dan STA yang konsisten.")
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
    st.button("↺ Muat data contoh", on_click=_muat_contoh)
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
    fig = plot_trase(tr)
    st.pyplot(fig)
    with st.expander("Tabel stasioning lengkap"):
        st.dataframe(pd.DataFrame([(n, fmt_sta(s), f"{s:.3f}") for n, s in tr["tabel_sta"]],
                                  columns=["Titik", "STA", "STA (m)"]), hide_index=True, use_container_width=True)
    st.info("Langkah berikutnya: buka **🔄 Hitung Tikungan** dan pilih *Ambil dari trase* untuk melihat rincian hitungan satu PI.")


# =============================================================================
#  HALAMAN 4 : HITUNG TIKUNGAN
# =============================================================================
def tampil_hasil(A):
    P, hasil, terpilih = A["P"], A["hasil"], A["terpilih"]
    dasar = A["dasar"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("f (koef. gesek)", f"{dasar['f']:.3f}")
    c2.metric("Rmin", f"{dasar['Rmin']:.2f} m", "Rc memenuhi ✔" if dasar["R_ok"] else "Rc < Rmin ✘",
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
        with st.expander(f"{'✅' if hh['ok'] else '⚠️'} {nama_lengkap[tp]}{'  — DIPAKAI' if tp == terpilih else ''}",
                         expanded=(tp == terpilih)):
            for ps in hh["pesan"]:
                st.warning(ps)
            if not hh["pesan"]:
                st.success("Semua syarat terpenuhi.")
            st.dataframe(df_hasil(hh["rows"], teks=True), use_container_width=True, hide_index=True)


def halaman_tikungan():
    judul_halaman("🔄", "Hitung Tikungan", "Bandingkan Full Circle, Spiral-Circle-Spiral, dan Spiral-Spiral berdampingan.")
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
        st.caption("Ubah R, Vr, atau jenis tikungan di menu 📏 Jarak, Azimut & STA.")
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
    tampil_hasil(tikungan_aktif())


# =============================================================================
#  HALAMAN 5 : PELEBARAN
# =============================================================================
def halaman_pelebaran():
    judul_halaman("↔️", "Pelebaran Perkerasan", "Kebutuhan pelebaran lajur di tikungan menurut kendaraan rencana.")
    A = tikungan_aktif()
    P = A["P"]
    st.caption(f"R = {P['Rc']:g} m dan Vr = {P['Vr']:g} km/jam mengikuti menu 🔄 Hitung Tikungan.")
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
    judul_halaman("👁️", "Jarak Pandang", "Jarak pandang henti (JPH) dan mendahului (JPM) dibandingkan dengan standar.")
    A = tikungan_aktif()
    vr = A["P"]["Vr"]
    st.caption(f"Vr = {vr:g} km/jam mengikuti menu 🔄 Hitung Tikungan.")
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
def _item(nama, h, P, arah="-"):
    return dict(h=h, P=P, peleb=aman_peleb(P, P["Rc"], P["Vr"]), judul=f"{nama} - {label_pendek(h['tipe'])}", arah=arah)


def halaman_output():
    judul_halaman("📤", "Gambar CAD & Excel", "Pratinjau gambar lalu unduh file .dxf untuk AutoCAD dan .xlsx berumus.")
    tr = trase_hasil()
    pis_ok = [p for p in tr["pi"] if not p["lurus"]]
    opsi = ["Tikungan aktif (menu Hitung Tikungan)"] + (["Seluruh tikungan pada trase"] if pis_ok else [])
    mode = in_sel("Yang digambar", "mode_out", opsi, radio=True)
    A = tikungan_aktif()
    items = []
    if mode.startswith("Tikungan aktif"):
        semua = in_chk("Gambar FC, SCS, dan SS sekaligus (satu lembar per jenis)", "semua")
        nama = A["info"]["nama"] if A["info"] else "TIKUNGAN"
        arah = A["info"]["arah"] if A["info"] else "-"
        jenis_list = ["FC", "SCS", "SS"] if semua else [A["terpilih"]]
        for t in jenis_list:
            if t == "SCS" and A["hasil"]["SCS"]["v"]["thc"] <= 0:
                st.warning("SCS tidak dapat digambar karena θc ≤ 0, dilewati.")
                continue
            items.append(_item(nama, A["hasil"][t], A["P"], arah))
    else:
        for p in pis_ok:
            if p["jenis"] == "SCS" and p["h"]["v"]["thc"] <= 0:
                st.warning(f"{p['nama']}: SCS tidak valid (θc ≤ 0), tidak digambar.")
                continue
            items.append(_item(p["nama"], p["h"], p["P"], p["arah"]))

    st.subheader("Pratinjau gambar")
    dxf_bytes, doc = None, None
    if items:
        dxf_bytes, doc = buat_dxf(items)
        try:
            st.image(pratinjau_png(doc), caption="Pratinjau (isi file .dxf yang sama)", use_container_width=True)
        except Exception as e:
            st.info(f"Pratinjau tidak tersedia ({e}). File DXF tetap bisa diunduh dan dibuka di AutoCAD.")
        st.caption(f"{len(items)} lembar A3 berjajar ke kanan. Satuan lembar: mm, skala tertera di tiap lembar.")
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
    xlsx = buat_excel(A["P"], A["sta_pi"], A["terpilih"], jp, rows, V("sta_awal")) if len(rows) >= 2 else None

    st.divider()
    d1, d2 = st.columns(2)
    if xlsx:
        d1.download_button("📥 Download Excel (.xlsx)", xlsx, file_name="GeoJalan_Hitungan.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    if dxf_bytes:
        d2.download_button("📥 Download CAD (.dxf)", dxf_bytes, file_name="GeoJalan_Gambar.dxf",
                           mime="application/dxf", use_container_width=True)
    st.info(
        "**Isi Excel:** sheet *Parameter* (FC, SCS, SS), *Pelebaran*, *Jarak Pandang*, dan *Trase & STA*. "
        "Sel biru berlatar kuning = input yang boleh diubah; sel lain berisi rumus Excel yang menghitung otomatis."
    )


# =============================================================================
#  MAIN
# =============================================================================
def main():
    st.set_page_config(page_title="GeoJalan – Kalkulator Geometri Tikungan Jalan", page_icon="🛣️", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="topbar"><div class="brand"><div class="logo">🛣️</div>'
        '<div><b>GeoJalan</b><small>Kalkulator tikungan FC · SCS · SS</small></div></div></div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("menu") not in PAGES:
        st.session_state["menu"] = PAGES[0]
    with st.container(key="nav"):
        for c, p in zip(st.columns(len(PAGES)), PAGES):
            c.button(NAV[p], key=f"nav_{p}", on_click=_ke, args=(p,), use_container_width=True,
                     type="primary" if st.session_state["menu"] == p else "secondary")
    page = st.session_state["menu"]
    if st.session_state.get("_prev_page") != page:
        st.session_state["_prev_page"] = page
        if page == PAGES[2]:
            st.session_state["trase_base"] = trase_df()
            st.session_state.pop("w_trase_editor", None)
    {
        PAGES[0]: halaman_beranda, PAGES[1]: halaman_materi, PAGES[2]: halaman_trase, PAGES[3]: halaman_tikungan,
        PAGES[4]: halaman_pelebaran, PAGES[5]: halaman_jarak_pandang, PAGES[6]: halaman_output,
    }[page]()
    if page != PAGES[0]:
        st.markdown(
            '<div class="foot"><b>GeoJalan</b> · Alat bantu hitung alinyemen horizontal. '
            'Periksa hasil terhadap pedoman yang berlaku sebelum dipakai untuk desain.</div>',
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
