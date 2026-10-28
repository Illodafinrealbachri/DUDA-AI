import os
import mysql.connector
from mysql.connector import Error as MySQLError
from pathlib import Path
from datetime import date, datetime
import calendar

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# =========================
# CONFIGURATION
# =========================
st.set_page_config(
    page_title="DUDA | Duit Digital dengan AI",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)

ROOT = Path(__file__).resolve().parent
# Konfigurasi XAMPP MariaDB/MySQL. Bisa dioverride lewat environment variables.
DB_CONFIG = {
    "host": os.getenv("DUDA_DB_HOST", "localhost"),
    "port": int(os.getenv("DUDA_DB_PORT", "3306")),
    "user": os.getenv("DUDA_DB_USER", "root"),
    "password": os.getenv("DUDA_DB_PASSWORD", ""),
    "database": os.getenv("DUDA_DB_NAME", "duda_db"),
    "charset": "utf8mb4",
    "use_unicode": True,
}
CSS_PATH = ROOT / "assets" / "style.css"

if CSS_PATH.exists():
    st.markdown(
        f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )

CATEGORIES = [
    "Makan", "Transportasi", "Pendidikan", "Hiburan",
    "Tagihan", "Kesehatan", "Belanja", "Gaji/Uang Bulanan",
    "Usaha", "Beasiswa", "Lainnya",
]
EXPENSE_CATEGORIES = [
    "Makan", "Transportasi", "Pendidikan", "Hiburan",
    "Tagihan", "Kesehatan", "Belanja", "Lainnya",
]


# =========================
# DATABASE (MySQL/MariaDB via XAMPP)
# =========================
def db_connection():
    """Buka koneksi baru ke database DUDA di XAMPP."""
    return mysql.connector.connect(**DB_CONFIG)


def init_db():
    """Buat tabel yang dibutuhkan jika belum tersedia; tidak menghapus data lama."""
    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                type VARCHAR(30) NOT NULL,
                amount BIGINT NOT NULL,
                category VARCHAR(100) NOT NULL,
                date DATE NOT NULL,
                description TEXT DEFAULT NULL,
                INDEX idx_transactions_date (date),
                INDEX idx_transactions_type (type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                month CHAR(7) NOT NULL,
                category VARCHAR(100) NOT NULL,
                amount BIGINT NOT NULL,
                UNIQUE KEY uq_budgets_month_category (month, category)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                `key` VARCHAR(100) NOT NULL PRIMARY KEY,
                `value` TEXT NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.execute("""
            INSERT IGNORE INTO settings (`key`, `value`) VALUES (%s, %s)
        """, ("username", "Alex"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def get_setting(key, default=""):
    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT `value` FROM settings WHERE `key` = %s", (key,))
        row = cursor.fetchone()
        return row[0] if row else default
    finally:
        cursor.close()
        conn.close()


def save_setting(key, value):
    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO settings (`key`, `value`) VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
        """, (key, str(value)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def get_transactions():
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM transactions ORDER BY date DESC, id DESC")
        rows = cursor.fetchall()
        df = pd.DataFrame(rows, columns=["id", "type", "amount", "category", "date", "description"])
    finally:
        cursor.close()
        conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
    return df


def get_budgets(month):
    conn = db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT category, amount FROM budgets WHERE month = %s ORDER BY category",
            (month,)
        )
        rows = cursor.fetchall()
        return pd.DataFrame(rows, columns=["category", "amount"])
    finally:
        cursor.close()
        conn.close()


def add_transaction(tx_type, amount, category, tx_date, description):
    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO transactions (`type`, amount, category, `date`, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (tx_type, int(amount), category, tx_date.isoformat(), description.strip()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def save_budget(month, category, amount):
    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO budgets (month, category, amount) VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE amount = VALUES(amount)
        """, (month, category, int(amount)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def delete_transaction(transaction_id):
    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM transactions WHERE id = %s", (int(transaction_id),))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def delete_budget(month, category):
    conn = db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM budgets WHERE month = %s AND category = %s",
            (month, category)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


# =========================
# HELPERS
# =========================
def rupiah(value):
    return "Rp" + f"{int(value):,}".replace(",", ".")


def money_delta(value):
    return f"{'+' if value >= 0 else '-'}{rupiah(abs(value))}"


def month_label(month_string):
    try:
        dt = datetime.strptime(month_string, "%Y-%m")
        names = [
            "Januari", "Februari", "Maret", "April", "Mei", "Juni",
            "Juli", "Agustus", "September", "Oktober", "November", "Desember"
        ]
        return f"{names[dt.month - 1]} {dt.year}"
    except ValueError:
        return month_string


def apply_month(df, month_string):
    if df.empty:
        return df.copy()
    return df[df["date"].dt.strftime("%Y-%m") == month_string].copy()


def rule_recommendations(income, expense, budgets, month_df, elapsed_days, days_in_month):
    recommendations = []
    if income > 0 and expense > income:
        recommendations.append(("danger", "Pengeluaran melebihi pemasukan",
            "Pengeluaran bulan ini sudah lebih besar daripada pemasukan. Tinjau kebutuhan non-prioritas dan hindari pengeluaran yang bisa ditunda."))
    elif income > 0:
        recommendations.append(("success", "Arus kas masih positif",
            f"Sisa dana berdasarkan transaksi yang tercatat adalah {rupiah(income - expense)}. Tetap sisihkan dana untuk kebutuhan penting."))

    if not budgets.empty:
        for _, budget in budgets.iterrows():
            cat = str(budget["category"])
            limit = int(budget["amount"])
            spent = int(month_df.loc[
                (month_df["type"] == "Pengeluaran") &
                (month_df["category"] == cat), "amount"
            ].sum())
            ratio = spent / limit if limit else 0
            if ratio > 1:
                recommendations.append(("danger", f"Anggaran {cat} terlampaui",
                    f"Pengeluaran {rupiah(spent)} telah melewati batas {rupiah(limit)}. Kurangi transaksi yang tidak mendesak untuk kategori ini."))
            elif ratio >= 0.8:
                recommendations.append(("warning", f"Anggaran {cat} hampir habis",
                    f"{ratio:.0%} anggaran telah digunakan ({rupiah(spent)} dari {rupiah(limit)}). Batasi pengeluaran berikutnya."))
            else:
                recommendations.append(("success", f"Anggaran {cat} terkendali",
                    f"Baru {ratio:.0%} anggaran yang digunakan. Pertahankan kebiasaan belanja ini."))

    if expense > 0 and elapsed_days > 0:
        projected = expense / elapsed_days * days_in_month
        if income > 0 and projected > income:
            recommendations.append(("warning", "Proyeksi pengeluaran perlu diperhatikan",
                f"Jika laju harian tetap, pengeluaran diperkirakan mencapai {rupiah(projected)} pada akhir bulan, lebih tinggi dari pemasukan saat ini."))
        else:
            recommendations.append(("info", "Proyeksi pengeluaran bulanan",
                f"Dengan asumsi pengeluaran harian tetap, proyeksi pengeluaran akhir bulan sekitar {rupiah(projected)}."))

    if not recommendations:
        recommendations.append(("info", "Mulai catat aktivitas keuangan",
            "Tambahkan pemasukan, pengeluaran, dan anggaran agar DUDA dapat memberikan analisis yang lebih relevan."))
    return recommendations


# =========================
# INITIALIZE + CURRENT STATE
# =========================
try:
    init_db()
except MySQLError as exc:
    st.error(
        "DUDA belum bisa terhubung ke MySQL/MariaDB. Pastikan MySQL di XAMPP berstatus Running, "
        "database `duda_db` tersedia, dan konfigurasi di bagian atas `app.py` sesuai. "
        f"Detail: {exc}"
    )
    st.stop()

today = date.today()
current_month = today.strftime("%Y-%m")
days_in_month = calendar.monthrange(today.year, today.month)[1]
elapsed_days = today.day
username = get_setting("username", "Alex")
all_transactions = get_transactions()

# Sidebar
with st.sidebar:
    st.markdown(
        '<div class="brand"><span class="brand-mark">D</span><span>DUDA</span></div>',
        unsafe_allow_html=True,
    )
    st.caption("DUIT DIGITAL DENGAN AI")
    st.markdown('<div class="nav-label">MENU UTAMA</div>', unsafe_allow_html=True)
    page = st.radio(
        "Navigasi",
        ["Dashboard", "Transaksi", "Anggaran", "Analisis AI", "Pengaturan"],
        label_visibility="collapsed",
        key="navigation",
    )
    st.markdown("---")
    st.markdown(
        f'<div class="profile-chip"><div class="avatar">{(username[:1] or "A").upper()}</div>'
        f'<div><div class="profile-name">{username}</div>'
        '<div class="profile-role">Pengelola keuangan</div></div></div>',
        unsafe_allow_html=True,
    )
    st.caption("DUDA • Versi 1.0")


# Month filter in header, applies to financial pages
head_left, head_right = st.columns([3, 1.2])
with head_left:
    greeting_hour = datetime.now().hour
    greeting = "Selamat pagi" if greeting_hour < 11 else (
        "Selamat siang" if greeting_hour < 15 else (
            "Selamat sore" if greeting_hour < 18 else "Selamat malam"
        )
    )
    if page == "Dashboard":
        st.markdown(
            f'<div class="eyebrow">DASHBOARD KEUANGAN</div>'
            f'<div class="hero-title">{greeting}, {username} 👋</div>'
            '<div class="hero-subtitle">Berikut ringkasan kondisi keuanganmu.</div>',
            unsafe_allow_html=True,
        )
    else:
        titles = {
            "Transaksi": ("Transaksi", "Catat dan kelola semua aktivitas keuanganmu."),
            "Anggaran": ("Anggaran Bulanan", "Rencanakan pengeluaran agar tetap terkendali."),
            "Analisis AI": ("Analisis & Rekomendasi AI", "Insight berbasis aturan dari data keuanganmu."),
            "Pengaturan": ("Pengaturan", "Personalisasi aplikasi DUDA."),
        }
        title, subtitle = titles[page]
        st.markdown(
            f'<div class="eyebrow">DUDA / {page.upper()}</div>'
            f'<div class="hero-title">{title}</div>'
            f'<div class="hero-subtitle">{subtitle}</div>',
            unsafe_allow_html=True,
        )
with head_right:
    month_options = []
    for offset in range(12):
        year = today.year
        month = today.month - offset
        while month <= 0:
            month += 12
            year -= 1
        month_options.append(f"{year:04d}-{month:02d}")
    selected_month = st.selectbox(
        "Periode", month_options,
        format_func=month_label,
        key="selected_month",
    )

month_df = apply_month(all_transactions, selected_month)
income = int(month_df.loc[month_df["type"] == "Pemasukan", "amount"].sum()) if not month_df.empty else 0
expense = int(month_df.loc[month_df["type"] == "Pengeluaran", "amount"].sum()) if not month_df.empty else 0
balance = income - expense
savings_rate = ((income - expense) / income * 100) if income > 0 else 0
budgets = get_budgets(selected_month)

st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)


# =========================
# DASHBOARD
# =========================
if page == "Dashboard":
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown('<div class="metric-label">SALDO BERSIH</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-value">{rupiah(balance)}</div>', unsafe_allow_html=True)
        st.markdown('<div class="metric-foot positive">● Saldo periode terpilih</div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="metric-label">TOTAL PEMASUKAN</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-value">{rupiah(income)}</div>', unsafe_allow_html=True)
        st.markdown('<div class="metric-foot">Pemasukan tercatat</div>', unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="metric-label">TOTAL PENGELUARAN</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-value">{rupiah(expense)}</div>', unsafe_allow_html=True)
        st.markdown('<div class="metric-foot negative">Pengeluaran tercatat</div>', unsafe_allow_html=True)
    with c4:
        st.markdown('<div class="metric-label">TINGKAT TABUNGAN</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-value">{savings_rate:.1f}%</div>', unsafe_allow_html=True)
        st.markdown('<div class="metric-foot positive">Pemasukan dikurangi pengeluaran</div>', unsafe_allow_html=True)

    left, right = st.columns([1.8, 1], gap="large")
    with left:
        st.markdown('<div class="section-heading">Arus Kas</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">Pemasukan dan pengeluaran selama 6 bulan terakhir</div>', unsafe_allow_html=True)
        months = []
        for offset in reversed(range(6)):
            year = today.year
            month = today.month - offset
            while month <= 0:
                month += 12
                year -= 1
            months.append(f"{year:04d}-{month:02d}")
        flow_rows = []
        for m in months:
            mdf = apply_month(all_transactions, m)
            inc = int(mdf.loc[mdf["type"] == "Pemasukan", "amount"].sum()) if not mdf.empty else 0
            exp = int(mdf.loc[mdf["type"] == "Pengeluaran", "amount"].sum()) if not mdf.empty else 0
            flow_rows.append({"Bulan": month_label(m)[:3], "Pemasukan": inc, "Pengeluaran": exp})
        flow_df = pd.DataFrame(flow_rows)
        if PLOTLY_AVAILABLE:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=flow_df["Bulan"], y=flow_df["Pemasukan"], name="Pemasukan",
                mode="lines+markers", line=dict(color="#00E6A0", width=3, shape="spline"),
                fill="tozeroy", fillcolor="rgba(0,230,160,0.10)"
            ))
            fig.add_trace(go.Scatter(
                x=flow_df["Bulan"], y=flow_df["Pengeluaran"], name="Pengeluaran",
                mode="lines+markers", line=dict(color="#FF5277", width=2, shape="spline"),
                fill="tozeroy", fillcolor="rgba(255,82,119,0.06)"
            ))
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=12, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#A7A9C4", size=11),
                legend=dict(orientation="h", y=1.15, x=0),
                xaxis=dict(showgrid=False, zeroline=False),
                yaxis=dict(showgrid=True, gridcolor="rgba(130,140,180,0.12)", zeroline=False, tickprefix="Rp"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Untuk grafik interaktif, jalankan: python -m pip install plotly")
            st.dataframe(flow_df, use_container_width=True, hide_index=True)

    with right:
        st.markdown('<div class="section-heading">Komposisi Pengeluaran</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">Berdasarkan kategori</div>', unsafe_allow_html=True)
        cat_df = month_df[month_df["type"] == "Pengeluaran"].groupby("category", as_index=False)["amount"].sum() if not month_df.empty else pd.DataFrame(columns=["category", "amount"])
        if not cat_df.empty and PLOTLY_AVAILABLE:
            fig = px.pie(cat_df, names="category", values="amount", hole=0.68,
                         color_discrete_sequence=["#00E6A0", "#4C9AFF", "#A78BFA", "#FFC857", "#FF5277", "#36C9C6", "#F08A5D"])
            fig.update_traces(textinfo="none", marker=dict(line=dict(color="#111222", width=3)))
            fig.update_layout(
                height=245, margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True, legend=dict(font=dict(color="#B5B7D0", size=10), orientation="h", y=-0.08),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown(f'<div class="donut-total">{rupiah(expense)}</div><div class="donut-caption">total pengeluaran</div>', unsafe_allow_html=True)
        elif not cat_df.empty:
            st.dataframe(cat_df, use_container_width=True, hide_index=True)
        else:
            st.markdown('<div class="empty-state">Belum ada pengeluaran pada periode ini.</div>', unsafe_allow_html=True)

    lower_left, lower_right = st.columns([1.2, 1], gap="large")
    with lower_left:
        st.markdown('<div class="section-heading">Transaksi Terbaru</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">Aktivitas keuangan terakhir pada periode ini</div>', unsafe_allow_html=True)
        if month_df.empty:
            st.markdown('<div class="empty-state">Belum ada transaksi. Tambahkan transaksi pertama melalui menu Transaksi.</div>', unsafe_allow_html=True)
        else:
            recent = month_df.head(5)
            for _, row in recent.iterrows():
                is_income = row["type"] == "Pemasukan"
                symbol = "+" if is_income else "−"
                color_class = "positive" if is_income else "negative"
                icon = "↗" if is_income else "↘"
                dt = row["date"].strftime("%d %b %Y") if pd.notna(row["date"]) else "-"
                st.markdown(
                    f'<div class="transaction-row"><div class="transaction-icon">{icon}</div>'
                    f'<div class="transaction-main"><div class="transaction-title">{row["description"] or row["category"]}</div>'
                    f'<div class="transaction-meta">{row["category"]} · {dt}</div></div>'
                    f'<div class="transaction-amount {color_class}">{symbol}{rupiah(row["amount"])}</div></div>',
                    unsafe_allow_html=True,
                )
    with lower_right:
        st.markdown('<div class="section-heading">Progres Anggaran</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">Penggunaan batas per kategori</div>', unsafe_allow_html=True)
        if budgets.empty:
            st.markdown('<div class="empty-state">Belum ada anggaran. Buka menu Anggaran untuk menetapkan batas pengeluaran.</div>', unsafe_allow_html=True)
        else:
            for _, row in budgets.iterrows():
                cat = row["category"]
                limit = int(row["amount"])
                spent = int(month_df.loc[
                    (month_df["type"] == "Pengeluaran") & (month_df["category"] == cat), "amount"
                ].sum()) if not month_df.empty else 0
                ratio = spent / limit if limit else 0
                state = "danger" if ratio > 1 else ("warning" if ratio >= .8 else "normal")
                st.markdown(
                    f'<div class="budget-row"><div class="budget-head"><span>{cat}</span>'
                    f'<span>{rupiah(spent)} / {rupiah(limit)}</span></div>'
                    f'<div class="budget-track"><div class="budget-fill {state}" style="width:{min(ratio*100,100):.1f}%"></div></div>'
                    f'<div class="budget-foot">{ratio:.0%} digunakan</div></div>',
                    unsafe_allow_html=True,
                )


# =========================
# TRANSACTIONS
# =========================
elif page == "Transaksi":
    form_col, tip_col = st.columns([1.1, 0.9], gap="large")
    with form_col:
        st.markdown('<div class="section-heading">Tambah Transaksi</div>', unsafe_allow_html=True)
        with st.form("add_transaction_form", clear_on_submit=True):
            tx_type = st.radio("Jenis transaksi", ["Pengeluaran", "Pemasukan"], horizontal=True)
            amount = st.number_input("Nominal (rupiah)", min_value=1, value=25000, step=1000)
            category = st.selectbox("Kategori", CATEGORIES)
            tx_date = st.date_input("Tanggal", value=today)
            description = st.text_input("Keterangan", placeholder="Contoh: makan siang")
            submitted = st.form_submit_button("Simpan Transaksi", type="primary", width="stretch")
            if submitted:
                add_transaction(tx_type, int(amount), category, tx_date, description)
                st.success("Transaksi berhasil disimpan.")
                st.rerun()
    with tip_col:
        st.markdown('<div class="section-heading">Ringkasan Periode</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="summary-panel"><div class="summary-line"><span>Pemasukan</span><b class="positive">{rupiah(income)}</b></div>'
            f'<div class="summary-line"><span>Pengeluaran</span><b class="negative">{rupiah(expense)}</b></div>'
            f'<div class="summary-line total"><span>Saldo</span><b>{rupiah(balance)}</b></div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-heading">Riwayat Transaksi</div>', unsafe_allow_html=True)
    filter_col, search_col = st.columns([1, 2])
    with filter_col:
        type_filter = st.selectbox("Filter jenis", ["Semua", "Pemasukan", "Pengeluaran"])
    with search_col:
        search_text = st.text_input("Cari transaksi", placeholder="Cari kategori atau keterangan...")
    history = month_df.copy()
    if type_filter != "Semua":
        history = history[history["type"] == type_filter]
    if search_text.strip():
        mask = (
            history["category"].astype(str).str.contains(search_text, case=False, na=False) |
            history["description"].astype(str).str.contains(search_text, case=False, na=False)
        )
        history = history[mask]
    export_df = history.copy()
    if not export_df.empty:
        export_df["date"] = export_df["date"].dt.strftime("%Y-%m-%d")
    st.download_button(
        "Unduh CSV",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"laporan_duda_{selected_month}.csv",
        mime="text/csv",
    )
    if history.empty:
        st.info("Tidak ada transaksi yang cocok dengan filter.")
    else:
        display = history[["id", "date", "type", "category", "amount", "description"]].copy()
        display["date"] = display["date"].dt.strftime("%d-%m-%Y")
        display["amount"] = display["amount"].map(rupiah)
        st.dataframe(display, use_container_width=True, hide_index=True, width="stretch")
        with st.expander("Hapus transaksi"):
            st.warning("Penghapusan tidak bisa dibatalkan.")
            tx_ids = history["id"].astype(int).tolist()
            chosen_id = st.selectbox("Pilih ID transaksi", tx_ids)
            if st.button("Hapus transaksi terpilih", type="secondary"):
                delete_transaction(chosen_id)
                st.success("Transaksi dihapus.")
                st.rerun()


# =========================
# BUDGETS
# =========================
elif page == "Anggaran":
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown('<div class="section-heading">Atur Anggaran</div>', unsafe_allow_html=True)
        with st.form("budget_form", clear_on_submit=True):
            budget_category = st.selectbox("Kategori pengeluaran", EXPENSE_CATEGORIES)
            budget_amount = st.number_input("Batas anggaran (rupiah)", min_value=1, value=300000, step=25000)
            save = st.form_submit_button("Simpan Anggaran", type="primary", width="stretch")
            if save:
                save_budget(selected_month, budget_category, int(budget_amount))
                st.success("Anggaran berhasil disimpan atau diperbarui.")
                st.rerun()
    with right:
        st.markdown('<div class="section-heading">Panduan Anggaran</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="rule-card"><span class="rule-dot green"></span><div><b>Di bawah 80%</b><p>Pengeluaran masih relatif terkendali.</p></div></div>'
            '<div class="rule-card"><span class="rule-dot yellow"></span><div><b>80% sampai 100%</b><p>Perlu berhati-hati karena anggaran hampir habis.</p></div></div>'
            '<div class="rule-card"><span class="rule-dot red"></span><div><b>Di atas 100%</b><p>Anggaran telah terlampaui.</p></div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-heading">Anggaran {month_label(selected_month)}</div>', unsafe_allow_html=True)
    if budgets.empty:
        st.info("Belum ada anggaran untuk periode ini.")
    else:
        for _, row in budgets.iterrows():
            cat = row["category"]
            limit = int(row["amount"])
            spent = int(month_df.loc[
                (month_df["type"] == "Pengeluaran") & (month_df["category"] == cat), "amount"
            ].sum()) if not month_df.empty else 0
            ratio = spent / limit if limit else 0
            state = "danger" if ratio > 1 else ("warning" if ratio >= .8 else "normal")
            a, b = st.columns([5, 1])
            with a:
                st.markdown(
                    f'<div class="budget-row"><div class="budget-head"><span>{cat}</span>'
                    f'<span>{rupiah(spent)} / {rupiah(limit)}</span></div>'
                    f'<div class="budget-track"><div class="budget-fill {state}" style="width:{min(ratio*100,100):.1f}%"></div></div>'
                    f'<div class="budget-foot">{ratio:.0%} digunakan · sisa {rupiah(max(limit-spent,0))}</div></div>',
                    unsafe_allow_html=True,
                )
            with b:
                if st.button("Hapus", key=f"delete_budget_{selected_month}_{cat}"):
                    delete_budget(selected_month, cat)
                    st.rerun()


# =========================
# AI ANALYSIS
# =========================
elif page == "Analisis AI":
    st.markdown(
        '<div class="ai-banner"><div class="ai-orb">✦</div><div><div class="ai-banner-title">DUDA Financial Insight</div>'
        '<div class="ai-banner-subtitle">Rekomendasi otomatis dari sistem berbasis aturan IF–THEN.</div></div></div>',
        unsafe_allow_html=True,
    )
    recs = rule_recommendations(income, expense, budgets, month_df, elapsed_days, days_in_month)
    for kind, title, body in recs:
        icon = {"danger": "!", "warning": "↗", "success": "✓", "info": "i"}.get(kind, "i")
        st.markdown(
            f'<div class="recommendation {kind}"><div class="recommendation-icon">{icon}</div>'
            f'<div><div class="recommendation-title">{title}</div>'
            f'<div class="recommendation-body">{body}</div></div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-heading">Aturan Sistem</div>', unsafe_allow_html=True)
    rules = pd.DataFrame([
        {"Kondisi": "Penggunaan anggaran < 80%", "Keputusan": "Status terkendali"},
        {"Kondisi": "Penggunaan anggaran 80–100%", "Keputusan": "Peringatan anggaran hampir habis"},
        {"Kondisi": "Penggunaan anggaran > 100%", "Keputusan": "Peringatan anggaran terlampaui"},
        {"Kondisi": "Pengeluaran > pemasukan", "Keputusan": "Evaluasi pengeluaran"},
        {"Kondisi": "Data pengeluaran tersedia", "Keputusan": "Proyeksi berdasarkan rata-rata harian"},
    ])
    st.dataframe(rules, use_container_width=True, hide_index=True)
    st.caption("Catatan: fitur rekomendasi ini adalah Rule-Based System, bukan model machine learning. Proyeksi mengasumsikan laju pengeluaran harian tetap.")


# =========================
# SETTINGS
# =========================
elif page == "Pengaturan":
    st.markdown('<div class="section-heading">Profil Pengguna</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Nama ini akan ditampilkan pada dashboard dan sidebar.</div>', unsafe_allow_html=True)
    with st.form("profile_form"):
        new_username = st.text_input("Username / nama panggilan", value=get_setting("username", "Alex"), max_chars=40)
        submitted = st.form_submit_button("Simpan Profil", type="primary", width="stretch")
        if submitted:
            clean_name = new_username.strip()
            if not clean_name:
                st.error("Nama tidak boleh kosong.")
            else:
                save_setting("username", clean_name)
                st.success("Profil berhasil diperbarui.")
                st.rerun()

    st.markdown('<div class="soft-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-heading">Tentang DUDA</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="summary-panel"><div class="summary-line"><span>Nama aplikasi</span><b>DUDA — Duit Digital dengan AI</b></div>'
        '<div class="summary-line"><span>Antarmuka</span><b>Python + Streamlit</b></div>'
        '<div class="summary-line"><span>Penyimpanan</span><b>MySQL / MariaDB (XAMPP)</b></div>'
        '<div class="summary-line"><span>Metode rekomendasi</span><b>Rule-Based System (IF–THEN)</b></div></div>',
        unsafe_allow_html=True,
    )
    st.caption("Jaga privasi data keuanganmu. Data DUDA disimpan di database MySQL/MariaDB XAMPP.")
