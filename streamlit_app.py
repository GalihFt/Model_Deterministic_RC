import streamlit as st
import pandas as pd
import numpy as np
from io import StringIO, BytesIO
from functools import reduce
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ==============================================================================
# KELAS KALKULATOR DETERMINISTIK (TIDAK BERUBAH)
# ==============================================================================
def extract_number(nocontainer):
    # Mengekstrak hanya digit dari string
    return ''.join(filter(str.isdigit, str(nocontainer)))

def get_container_size_grade(nocontainer):
    try:
        # Ekstrak hanya bagian numerik dari nomor kontainer
        numeric_part = extract_number(nocontainer)
        if not numeric_part:  # Jika tidak ada angka
            return "Others", "Others"
            
        nomor = int(numeric_part)
        if 2500000 <= nomor <= 2759999:
            return "20", "C"
        elif 2760000 <= nomor <= 2899999:
            return "20", "B"
        elif 2900000 <= nomor < 3500000:
            return "20", "A"
        elif 4600000 <= nomor <= 4619999:
            return "40", "C"
        elif 4620000 <= nomor < 4629999:
            return "40", "B"
        elif nomor >= 4630000:
            return "40", "A"
        else:
            return "Others", "Others"
    except:
        return "Others", "Others"

class DeterministicCostCalculator:
    """
    Menggantikan ContainerRepairPipeline.
    Kelas ini menghitung biaya perbaikan kontainer menggunakan logika bisnis
    deterministik, bukan model machine learning.
    """
    def __init__(self, master_material_df: pd.DataFrame):
        self.master_material = master_material_df
        self.depo_config = {
            "SBY": {"vendors": ['MTCP', 'SPIL']},
            "JKT": {"vendors": ['MDS', 'SPIL', 'MDSBC', 'MACBC', 'PTMAC', 'MCPNL', 'MCPCONCH']}
        }
        self.labourvendor_dict = {
            "MACBC": 29000, "MCPCONCH": 29000, "MCPNL": 15000,
            "MDS": 29000, "MDSBC": 29000, "MTCP": 15000,
            "PTMAC": 29000, "SPIL": 14000
        }
        self.surcharge_vendor = ["MCPCONCH", "MCPNL", "MDS", "MTCP", "PTMAC"]
        self.validity_map = {
            "JKT": {'MDS': ['A','Others'], 'SPIL': ['A', 'B', 'C','Others'], 'MDSBC': ['B', 'C','Others'], 'MACBC': ['B', 'C','Others'], 'PTMAC': ['A','Others'], 'MCPNL': ['A', 'B', 'C','Others'], 'MCPCONCH': ['B', 'C','Others']},
            "SBY": {'MTCP': ['A', 'B', 'C','Others'], 'SPIL': ['A', 'B', 'C','Others']}
        }

    def run_pipeline(self, input_data: pd.DataFrame) -> pd.DataFrame:
        """
        Fungsi utama yang menjalankan seluruh proses kalkulasi.
        Nama fungsi 'run_pipeline' dipertahankan agar kompatibel dengan sisa dashboard.
        """
        # Hitung jumlah material yang tidak ada di master sebelum merge
        input_data['WARNING'] = input_data['MATERIAL'].apply(
            lambda x: 0 if x in self.master_material['MATERIAL'].values else 1
        )
        
        df_merged = pd.merge(input_data, self.master_material, on="MATERIAL", how="left")
        
        # Hitung total warning per EOR
        warning_counts = input_data.groupby('NO_EOR')['WARNING'].sum().reset_index()
        warning_counts.rename(columns={'WARNING': 'WARNING_COUNT'}, inplace=True)
        
        base_cols = input_data[['NO_EOR', 'CONTAINER_GRADE', 'CONTAINER_TYPE', 'DEPO']].drop_duplicates(subset=['NO_EOR'])
        all_results_df = base_cols.set_index('NO_EOR')

        for depo in df_merged["DEPO"].unique():
            df_depo = df_merged[df_merged["DEPO"] == depo].copy()
            if df_depo.empty:
                continue
            vendors = self.depo_config.get(depo, {}).get("vendors", [])
            if not vendors:
                continue
            
            df_expanded = df_depo.loc[df_depo.index.repeat(len(vendors))].copy()
            df_expanded["IDKONTRAKTOR"] = np.tile(vendors, len(df_depo))
            # 1. Tetapkan biaya default untuk semua vendor dari dictionary
            #    SPIL SBY akan otomatis mendapatkan harga 14.000 dari sini.
            df_expanded["LABOURVENDOR"] = df_expanded["IDKONTRAKTOR"].map(self.labourvendor_dict)

            # 2. Buat kondisi spesifik untuk SPIL di JKT
            kondisi_spil_jkt = (df_expanded["IDKONTRAKTOR"] == "SPIL") & (df_expanded["DEPO"] == "JKT")

            # 3. Timpa (overwrite) nilainya menjadi 21.500 hanya jika kondisi di atas terpenuhi
            df_expanded.loc[kondisi_spil_jkt, "LABOURVENDOR"] = 21500
            df_expanded["MHR"] = np.where(
                df_expanded["IDKONTRAKTOR"] == "SPIL",
                df_expanded["MHR_SPIL"],
                df_expanded["MHR_VENDOR"]
            )
            df_expanded["SURCHARGE_FIX"] = np.where(
                df_expanded["IDKONTRAKTOR"].isin(self.surcharge_vendor),
                df_expanded["SURCHARGE"],
                0
            )
            num_cols_to_fill = ['QTY', 'MHR', 'LABOURVENDOR', 'COSTMATERIAL', 'SURCHARGE_FIX']
            for col in num_cols_to_fill:
                df_expanded[col] = pd.to_numeric(df_expanded[col], errors='coerce').fillna(0)
            df_expanded["HARGA_TOTAL"] = df_expanded["QTY"] * (
                df_expanded["MHR"] * df_expanded["LABOURVENDOR"] +
                df_expanded["COSTMATERIAL"] +
                df_expanded["SURCHARGE_FIX"]
            )
            grouped = df_expanded.groupby(["NO_EOR", "IDKONTRAKTOR"]).agg(
                MHRTOTAL=("MHR", "sum"),
                HARGATOTAL=("HARGA_TOTAL", "sum")
            ).reset_index()
            df_pivot = grouped.pivot(
                index="NO_EOR",
                columns="IDKONTRAKTOR",
                values=["MHRTOTAL", "HARGATOTAL"]
            )
            df_pivot.columns = [f"{val}_{col}" for val, col in df_pivot.columns]
            all_results_df = all_results_df.join(df_pivot, how='left')

        all_results_df = all_results_df.reset_index()
        rename_map = {col: col.replace('HARGATOTAL_', 'PREDIKSI_').replace('MHRTOTAL_', 'MHR_') for col in all_results_df.columns}
        final_df = all_results_df.rename(columns=rename_map)

        # ...di dalam fungsi run_pipeline
        for depo in final_df["DEPO"].unique():
            for vendor in self.depo_config.get(depo, {}).get("vendors", []):
                pred_col = f"PREDIKSI_{vendor}"
                mhr_col = f"MHR_{vendor}"
                if pred_col in final_df.columns and mhr_col in final_df.columns:
                    # --- PERUBAHAN DI SINI ---
                    # Gunakan np.where untuk menangani MHR nol secara aman
                    ratio = np.where(
                        final_df[mhr_col] > 0,              # Kondisi: jika MHR lebih dari 0
                        final_df[pred_col] / final_df[mhr_col], # Lakukan pembagian jika benar
                        np.nan                              # Jika tidak (MHR=0), hasilnya NaN
                    )
                    final_df[f"PREDIKSI/MHR_{vendor}"] = ratio
                    # --- AKHIR PERUBAHAN ---

        for idx, row in final_df.iterrows():
            depo = row['DEPO']
            grade = row['CONTAINER_GRADE']
            for vendor in self.depo_config.get(depo, {}).get("vendors", []):
                valid_grades = self.validity_map.get(depo, {}).get(vendor, [])
                if grade not in valid_grades:
                    for col_prefix in ["PREDIKSI_", "MHR_", "PREDIKSI/MHR_"]:
                        col_name = f"{col_prefix}{vendor}"
                        if col_name in final_df.columns:
                            final_df.loc[idx, col_name] = np.nan
                            
        # Gabungkan warning count ke final_df
        final_df = pd.merge(final_df, warning_counts, on='NO_EOR', how='left')
        final_df['WARNING_COUNT'] = final_df['WARNING_COUNT'].fillna(0).astype(int)
        
        return final_df
    
# ==============================================================================
# UI STREAMLIT DAN LOGIKA APLIKASI
# ==============================================================================
@st.cache_data
def load_master_data():
    try:
        scope = ["https://spreadsheets.google.com/feeds",'https://www.googleapis.com/auth/drive']
        # IMPORTANT: Replace "daring-span-436113-t5-9d44f9437abd.json" with the actual name of your JSON keyfile.
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            st.secrets["google_service_account"], scope
        )
        
        client = gspread.authorize(creds)

        # Replace with your Spreadsheet ID
        spreadsheet_id = "1llPtY1eX2j3tf8yaUGKc56M4EnbjPGpGf5ATVvN1_OQ"
        sheet = client.open_by_key(spreadsheet_id).sheet1

        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        # --- PERBAIKAN ---
        # Membersihkan spasi ekstra dari kolom MATERIAL untuk memastikan pencocokan yang akurat
        if 'MATERIAL' in df.columns:
            df['MATERIAL'] = df['MATERIAL'].astype(str).str.strip()
        return df
    
    except Exception as e:
        st.error(f"Terjadi error saat mengambil master material: {e}")
        return None


@st.cache_resource
def get_pipeline(_master_material_df):
    """Membuat instance kalkulator deterministik dan menyimpannya di cache."""
    if _master_material_df is None:
        return None
    pipeline = DeterministicCostCalculator(master_material_df=_master_material_df)
    return pipeline

st.set_page_config(page_title="Container Repair Allocation", layout="wide")
st.title("Dashboard Alokasi Perbaikan Kontainer")

master_material_df = load_master_data()
pipeline = get_pipeline(master_material_df)

if pipeline:
    with st.sidebar:
        st.header("⚙️ Parameter Global")
        depo_option = st.selectbox("Pilih DEPO", ["SBY","JKT"], key="global_depo")
        # Tambahkan tombol refresh
        if st.button("Refresh Data Master", help="Klik untuk memperbarui data master dari Google Sheet"):
            # Clear cache untuk memaksa reload data
            st.cache_data.clear()
            st.rerun()

        st.info("Pastikan master yang digunakan sudah terupdate.")

    tab_manual, tab_bulk = st.tabs(["Input Manual", "Input CSV & Alokasi"])

    with tab_manual:
        # KODE UNTUK TAB MANUAL (TIDAK BERUBAH)
        st.header("Estimasi Biaya Perbaikan")
        st.info("Masukkan detail perbaikan untuk satu kontainer untuk melihat perbandingan biaya antar vendor.")
        num_entries = st.number_input("Jumlah Item Kerusakan", min_value=1, max_value=30, value=3, help="Tentukan berapa banyak baris kerusakan yang akan Anda masukkan.", key="manual_num_entries")
        MATERIAL_OPTIONS = ["- Pilih Material -"] + sorted(master_material_df["MATERIAL"].dropna().unique().tolist())
        with st.form("manual_entry_form"):
            container_grade = st.selectbox("Kontainer Grade", ['A', 'B', 'C'], key="manual_grade")
            container_size = st.selectbox("Ukuran Kontainer", ['20', '40'], key="manual_size")
            damage_data = {'material': [], 'qty': []}
            cols_header = st.columns(2)
            cols_header[0].markdown("**Material**")
            cols_header[1].markdown("**Kuantitas**")
            for i in range(num_entries):
                cols = st.columns(2)
                damage_data['material'].append(cols[0].selectbox(f"Material_{i}", MATERIAL_OPTIONS, key=f"material_{i}", label_visibility="collapsed"))
                damage_data['qty'].append(cols[1].number_input(f"Qty_{i}", min_value=1, value=1, key=f"qty_{i}", label_visibility="collapsed"))
            submitted = st.form_submit_button("Cek Estimasi")
        if submitted:
            if any(opt.startswith("- Pilih") for opt in damage_data['material']):
                st.warning("Mohon pastikan semua item Material telah dipilih.")
            else:
                with st.spinner("Menghitung biaya..."):
                    manual_input_rows = []
                    for i in range(num_entries):
                        manual_input_rows.append({
                            "NO_EOR": "MANUAL_CHECK", "CONTAINER_SIZE": container_size, "CONTAINER_GRADE": container_grade,
                            "CONTAINER_TYPE": str(container_size) + str(container_grade), "MATERIAL": damage_data['material'][i],
                            "QTY": damage_data['qty'][i], "DEPO": depo_option
                        })
                    manual_df = pd.DataFrame(manual_input_rows)
                    try:
                        prediction_result = pipeline.run_pipeline(manual_df)
                        if not prediction_result.empty:
                            result_row = prediction_result.iloc[0]
                            st.subheader(f"Hasil Estimasi untuk DEPO {depo_option}")
                            
                            # Tampilkan warning count jika ada
                            if result_row['WARNING_COUNT'] > 0:
                                st.warning(f"⚠️ Ada {result_row['WARNING_COUNT']} material yang tidak ditemukan di data master dan tidak dihitung dalam estimasi.")
                            
                            display_data_list = []
                            for vendor in pipeline.depo_config.get(depo_option, {}).get("vendors", []):
                                display_data_list.append({
                                    "Vendor": vendor,
                                    "Prediksi Biaya": result_row.get(f"PREDIKSI_{vendor}", np.nan),
                                    "Estimasi MHR": result_row.get(f"MHR_{vendor}", np.nan),
                                    "Rasio Biaya/MHR": result_row.get(f"PREDIKSI/MHR_{vendor}", np.nan)
                                })
                            price_df = pd.DataFrame(display_data_list).dropna(subset=['Prediksi Biaya', 'Estimasi MHR'], how='all').sort_values(by="Prediksi Biaya", na_position='last')
                            if not price_df.empty:
                                st.dataframe(price_df.style.format({'Prediksi Biaya': 'Rp {:,.0f}', 'Estimasi MHR': '{:,.2f}', 'Rasio Biaya/MHR': 'Rp {:,.0f}/jam'}, na_rep='-'), use_container_width=True)
                            else:
                                st.error("Tidak ada prediksi yang valid untuk kombinasi Grade dan DEPO yang dipilih.")
                        else:
                            st.error("Gagal mendapatkan hasil perhitungan.")
                    except Exception as e:
                        st.error(f"Terjadi error saat perhitungan manual: {e}")

    # ==============================================================================
    # TAB 2: ALOKASI OPTIMAL (BULK) - LOGIKA BARU
    # ==============================================================================

    with tab_bulk:
        st.header("Alokasi Optimal untuk Perbaikan Kontainer")
        st.info("Pastikan file CSV, Excel, atau ODS yang diupload memiliki kolom: `NO_EOR`, `NOCONTAINER` , `MATERIAL`, `QTY`.")
        
        template_data = {
            'NO_EOR': [
                'EOR/00000004/01/2023',
                'EOR/00000004/01/2023',
                'EOR/00000004/01/2023',
                'EOR/00000005/01/2023',
                'EOR/00000005/01/2023',
                'EOR/00000005/01/2023'
            ],
            'NOCONTAINER': [
                'SPNU2839051',
                'SPNU2839051',
                'SPNU2839051',
                'SPNU2759465',
                'SPNU2759465',
                'SPNU2759465'
            ],
            'KETERANGAN': [
                'MISCELENEOUS - SECURING DEVICE / OTHER MATERIAL REMOVE',
                'CROSS MEMBER - INSERT 30 CM',
                'FORKLIFT POCKET - WEB STRAIGHTEN',
                'SIDE PANEL - STRAIGHTEN AND WELD 30 CM',
                'ROOF PANEL STRAIGHTEN AND WELD 30 CM',
                'SIDE PANEL - STRAIGHTEN 30 X 90 CM'
            ],
            'QTY': [1, 1, 2, 1, 1, 1]
        }
        template_df = pd.DataFrame(template_data)
        
        # Buat template Excel
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            template_df.to_excel(writer, index=False, sheet_name='Template')
        
        st.download_button(
            label="Download Template Excel",
            data=excel_buffer.getvalue(),
            file_name="template_alokasi_perbaikan.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Download template Excel dengan format yang benar"
        )

        # --- PERUBAHAN 1: Menambahkan tipe file yang didukung ---
        uploaded_file = st.file_uploader(
            "Upload file Anda (CSV, Excel, ODS)", 
            type=["csv", "xlsx", "xls", "ods"], 
            key="bulk_upload_spil"
        )
        
        allocation_method = st.selectbox(
            "Pilih Algoritma Alokasi",
            ("Prediksi Total", "Prediksi Harga per MHR"),
            key="alloc_method",
            help="**Prediksi Total**: Memprioritaskan kontainer dengan potensi penghematan biaya total terbesar. **Prediksi Harga per MHR**: Memprioritaskan kontainer dengan penghematan biaya per jam kerja (MHR) terbesar."
        )

        st.markdown("---")
        st.markdown("##### **Kapasitas SPIL**")
        col_toggle1, col_toggle2 = st.columns(2)
        use_container_filter = col_toggle1.toggle("Gunakan Filter Kapasitas Kontainer", value=True, key="toggle_container")
        use_mhr_filter = col_toggle2.toggle("Gunakan Filter Kapasitas MHR", value=True, key="toggle_mhr")
        
        col1_spil, col2_spil = st.columns(2)
        spil_container_capacity = col1_spil.number_input(f"Kapasitas Kontainer SPIL", min_value=0, value=100, key=f"today_container_spil", disabled=not use_container_filter)
        spil_mhr_capacity = col2_spil.number_input(f"Kapasitas MHR SPIL", min_value=0, value=5000, key=f"today_mhr_spil", format="%d", disabled=not use_mhr_filter)
        # --- AKHIR BAGIAN UTAMA ---


        # --- EXPANDER BARU UNTUK OPSI TAMBAHAN ---
        with st.expander("Opsi Tambahan (Waiting List & Vendor Lain)"):
            st.markdown("##### **Penanganan Sisa Pekerjaan**")
            use_waiting_list = st.checkbox("Gunakan Waiting List SPIL", key="use_waiting_list")
            tomorrow_capacities_input = {}
            if use_waiting_list:
                col1_wl, col2_wl = st.columns(2)
                tomorrow_container_capacity = col1_wl.number_input("Kapasitas Kontainer SPIL Besok", min_value=0, value=50, key="tomorrow_container_spil", disabled=not use_container_filter)
                tomorrow_mhr_capacity = col2_wl.number_input("Kapasitas MHR SPIL Besok", min_value=0, value=2500, key="tomorrow_mhr_spil", format="%d", disabled=not use_mhr_filter)
                tomorrow_capacities_input = {"kontainer": tomorrow_container_capacity, "mhr": tomorrow_mhr_capacity}

            st.markdown("---")
            use_other_vendors = st.checkbox("Gunakan Vendor Lain", key="use_other_vendors")
            other_vendor_capacities_input = {}
            if use_other_vendors:
                other_vendors = [v for v in pipeline.depo_config.get(depo_option, {}).get("vendors", []) if v != 'SPIL']
                for vendor in other_vendors:
                    st.markdown(f"**Kapasitas {vendor}**")
                    col1_other, col2_other = st.columns(2)
                    container_capacity = col1_other.number_input(f"Kapasitas Kontainer", min_value=0, value=100, key=f"other_container_{vendor}", disabled=not use_container_filter, label_visibility="collapsed")
                    mhr_capacity = col2_other.number_input(f"Kapasitas MHR", min_value=0, value=5000, key=f"other_mhr_{vendor}", format="%d", disabled=not use_mhr_filter, label_visibility="collapsed")
                    other_vendor_capacities_input[vendor] = {"kontainer": container_capacity, "mhr": mhr_capacity}
        # --- AKHIR EXPANDER ---


        st.markdown("---")
        run_bulk_button = st.button("Cek Alokasi", type="primary", key="spil_run")
        
        # --- PERUBAHAN 2: Memperbarui fungsi alokasi untuk menangani berbagai tipe file ---
        @st.cache_data
        def run_spil_centric_allocation(_pipeline, uploaded_file_content, file_name, depo_option, allocation_method, spil_today_cap, spil_tomorrow_cap, other_vendor_caps, use_wl, use_ov, use_container_filter, use_mhr_filter):
            try:
                file_extension = file_name.split('.')[-1].lower()
                
                # Membaca file berdasarkan ekstensinya
                if file_extension == 'csv':
                    content_str = uploaded_file_content.decode('utf-8')
                    # Coba baca dengan beberapa delimiter umum
                    for delimiter in [',', ';', '\t']:
                        try:
                            data_raw = pd.read_csv(StringIO(content_str), delimiter=delimiter)
                            break
                        except Exception:
                            continue
                    if 'data_raw' not in locals():
                         data_raw = pd.read_csv(StringIO(content_str), engine='python')
                elif file_extension in ['xlsx', 'xls']:
                    data_raw = pd.read_excel(BytesIO(uploaded_file_content))
                elif file_extension == 'ods':
                    data_raw = pd.read_excel(BytesIO(uploaded_file_content), engine='odf')
                else:
                    st.error(f"Format file tidak didukung: {file_extension}")
                    return pd.DataFrame()

                data_raw.columns = data_raw.columns.str.strip()
                
                if 'MATERIAL' in data_raw.columns:
                    data_raw['MATERIAL'] = data_raw['MATERIAL'].astype(str).str.strip()

                list_need = ['NO_EOR', 'NOCONTAINER', 'MATERIAL', 'QTY']
                missing_cols = [col for col in list_need if col not in data_raw.columns]
                if missing_cols:
                    st.error(f"Kolom berikut tidak ditemukan: {', '.join(missing_cols)}")
                    return pd.DataFrame()
                
                data = data_raw[list_need].copy()
                data[['CONTAINER_SIZE', 'CONTAINER_GRADE']] = data['NOCONTAINER'].apply(
                    lambda x: pd.Series(get_container_size_grade(x))
                )
                data['CONTAINER_TYPE'] = data['CONTAINER_SIZE'] + data['CONTAINER_GRADE']
                data["DEPO"] = depo_option
                
                raw_results = _pipeline.run_pipeline(data)
                if 'PREDIKSI_SPIL' not in raw_results.columns:
                    st.error("Perhitungan untuk SPIL tidak tersedia.")
                    return pd.DataFrame()

                if 'WARNING_COUNT' not in raw_results.columns:
                    raw_results['WARNING_COUNT'] = 0

                other_vendor_preds = [c for c in raw_results.columns if c.startswith('PREDIKSI_') and 'SPIL' not in c and not c.startswith('PREDIKSI/MHR_')]
                raw_results['Prediksi_Biaya_Lain'] = raw_results[other_vendor_preds].min(axis=1)
                raw_results['Selisih_Prediksi_Biaya'] = raw_results['Prediksi_Biaya_Lain'] - raw_results['PREDIKSI_SPIL']
                
                other_vendor_mhr_ratio = [c for c in raw_results.columns if c.startswith('PREDIKSI/MHR_') and 'SPIL' not in c]
                raw_results['HargaPerMHR_Lain'] = raw_results[other_vendor_mhr_ratio].min(axis=1)
                raw_results['Selisih_Harga_per_MHR'] = raw_results['HargaPerMHR_Lain'] - raw_results['PREDIKSI/MHR_SPIL']

                if allocation_method == 'Prediksi Harga per MHR':
                    sort_key = 'Selisih_Harga_per_MHR'
                else:
                    sort_key = 'Selisih_Prediksi_Biaya'
                
                spil_candidates = raw_results.sort_values(by=sort_key, ascending=False)
                allocations = {}
                spil_container_cap = spil_today_cap['kontainer'] if use_container_filter else float('inf')
                spil_mhr_cap = spil_today_cap['mhr'] if use_mhr_filter else float('inf')
                unallocated_eors = []
                
                for idx, row in spil_candidates.iterrows():
                    eor = row['NO_EOR']
                    mhr_needed = row.get('MHR_SPIL', 0)
                    if pd.isna(mhr_needed): mhr_needed = 0
                    if (not use_container_filter or spil_container_cap > 0) and (not use_mhr_filter or spil_mhr_cap >= mhr_needed):
                        if allocation_method == 'Prediksi Harga per MHR':
                            harga_final_value = row['PREDIKSI/MHR_SPIL']
                        else:
                            harga_final_value = row['PREDIKSI_SPIL']
                        allocations[eor] = {
                            'ALOKASI': 'SPIL', 
                            'HARGA_FINAL': harga_final_value
                        }
                        if use_container_filter: spil_container_cap -= 1
                        if use_mhr_filter: spil_mhr_cap -= mhr_needed
                    else:
                        unallocated_eors.append(eor)
                
                overflow_df = spil_candidates[spil_candidates['NO_EOR'].isin(unallocated_eors)].copy()
                
                if use_wl:
                    waiting_list_candidates = overflow_df.sort_values(by=sort_key, ascending=False)
                    spil_tomorrow_container_cap = spil_tomorrow_cap.get('kontainer', 0) if use_container_filter else float('inf')
                    spil_tomorrow_mhr_cap = spil_tomorrow_cap.get('mhr', 0) if use_mhr_filter else float('inf')
                    remaining_after_wl = []
                    for idx, row in waiting_list_candidates.iterrows():
                        eor = row['NO_EOR']
                        mhr_needed = row.get('MHR_SPIL', 0)
                        if pd.isna(mhr_needed): mhr_needed = 0
                        if (not use_container_filter or spil_tomorrow_container_cap > 0) and (not use_mhr_filter or spil_tomorrow_mhr_cap >= mhr_needed):
                            if allocation_method == 'Prediksi Harga per MHR':
                                harga_final_value = row['PREDIKSI/MHR_SPIL']
                            else:
                                harga_final_value = row['PREDIKSI_SPIL']
                            allocations[eor] = {
                                'ALOKASI': 'Waiting List SPIL', 
                                'HARGA_FINAL': harga_final_value
                            }
                            if use_container_filter: spil_tomorrow_container_cap -= 1
                            if use_mhr_filter: spil_tomorrow_mhr_cap -= mhr_needed
                        else:
                            remaining_after_wl.append(eor)
                    overflow_df = overflow_df[overflow_df['NO_EOR'].isin(remaining_after_wl)].copy()

                if use_ov:
                    other_vendor_candidates = overflow_df.sort_values(by=sort_key, ascending=True)
                    for idx, row in other_vendor_candidates.iterrows():
                        eor = row['NO_EOR']
                        allocated = False
                        cheapest_options = row[other_vendor_preds].dropna().sort_values()
                        for vendor_price_val in cheapest_options.items():
                            vendor_name = vendor_price_val[0].replace('PREDIKSI_', '')
                            mhr_needed = row.get(f'MHR_{vendor_name}', 0)
                            if pd.isna(mhr_needed): mhr_needed = 0
                            container_cap = other_vendor_caps.get(vendor_name, {}).get('kontainer', 0) if use_container_filter else float('inf')
                            mhr_cap = other_vendor_caps.get(vendor_name, {}).get('mhr', 0) if use_mhr_filter else float('inf')
                            if (not use_container_filter or container_cap > 0) and (not use_mhr_filter or mhr_cap >= mhr_needed):
                                if allocation_method == 'Prediksi Harga per MHR':
                                    harga_final_value = row.get(f'PREDIKSI/MHR_{vendor_name}', np.nan)
                                else:
                                    harga_final_value = vendor_price_val[1]
                                allocations[eor] = {
                                    'ALOKASI': f'{vendor_name}', 
                                    'HARGA_FINAL': harga_final_value
                                }
                                if use_container_filter: other_vendor_caps[vendor_name]['kontainer'] -= 1
                                if use_mhr_filter: other_vendor_caps[vendor_name]['mhr'] -= mhr_needed
                                allocated = True
                                break
                        if not allocated:
                            allocations[eor] = {
                                'ALOKASI': 'Tidak Terhandle', 
                                'HARGA_FINAL': np.nan
                            }
                else:
                    for eor in overflow_df['NO_EOR']:
                        allocations[eor] = {
                            'ALOKASI': 'Tidak Terhandle', 
                            'HARGA_FINAL': np.nan
                        }

                allocations_df = pd.DataFrame.from_dict(allocations, orient='index')
                final_df = raw_results.set_index('NO_EOR').join(allocations_df, how='left').reset_index()
                                    
                return final_df
            except Exception as e:
                st.error(f"Terjadi kesalahan saat memproses file: {e}")
                st.exception(e)
                return pd.DataFrame()

        if run_bulk_button and uploaded_file is not None:
            try:
                # --- PERUBAHAN 3: Menyesuaikan pemanggilan fungsi ---
                uploaded_file_content = uploaded_file.getvalue()
                file_name = uploaded_file.name
                spil_today_caps = {"kontainer": spil_container_capacity, "mhr": spil_mhr_capacity}
                with st.spinner(f'Menjalankan alokasi dengan algoritma "{allocation_method}"...'):
                    final_results = run_spil_centric_allocation(
                        pipeline, uploaded_file_content, file_name, depo_option, allocation_method,
                        spil_today_caps, tomorrow_capacities_input,
                        other_vendor_capacities_input, use_waiting_list, use_other_vendors,
                        use_container_filter, use_mhr_filter
                    )
                
                if not final_results.empty:
                    st.success("✅ Alokasi berhasil diselesaikan!")
                    
                    total_warnings = final_results['WARNING_COUNT'].sum()
                    if total_warnings > 0:
                        st.warning(f"⚠️ Total ada {int(total_warnings)} material yang tidak ditemukan di data master dan tidak dihitung dalam estimasi.")
                    
                    def get_final_mhr(row):
                        if pd.isna(row['ALOKASI']) or 'Tidak Terhandle' in row['ALOKASI']: return np.nan
                        if 'SPIL' in row['ALOKASI']: vendor = 'SPIL'
                        else: vendor = row['ALOKASI']
                        return row.get(f"MHR_{vendor}", np.nan)
                    final_results['MHR'] = final_results.apply(get_final_mhr, axis=1)

                    st.markdown("---")
                    st.subheader("Ringkasan Hasil Alokasi")
                    
                    vendor_stats = final_results.groupby('ALOKASI').agg(
                        Jumlah_Kontainer=('NO_EOR', 'nunique'),
                        Total_Biaya=('HARGA_FINAL', 'sum'),
                        Total_MHR=('MHR', 'sum'),
                        Total_Warning=('WARNING_COUNT', 'sum')
                    ).reset_index().rename(columns={
                        'ALOKASI': 'STATUS',
                        'Total_Biaya': 'Total Biaya',
                        'Jumlah_Kontainer': 'Jumlah Kontainer',
                        'Total_MHR': 'Total MHR',
                        'Total_Warning': 'Material Tidak Dikenali'
                    })

                    st.dataframe(vendor_stats.style.format({
                        "Total Biaya": "Rp {:,.0f}",
                        "Total MHR": "{:,.2f}",
                        "Material Tidak Dikenali": "{:,.0f}"
                    }), use_container_width=True)

                    st.markdown("---")
                    st.subheader("Detail Hasil Alokasi")
                    
                    if allocation_method == 'Prediksi Harga per MHR':
                        display_cols = ['NO_EOR', 'CONTAINER_TYPE', 'ALOKASI', 'HARGA_FINAL', 'MHR', 'Selisih_Harga_per_MHR', 'PREDIKSI/MHR_SPIL', 'HargaPerMHR_Lain', 'WARNING_COUNT']
                        rename_map_detail = {
                            'HARGA_FINAL': 'Harga/MHR Final', 'MHR': 'MHR Final', 'ALOKASI': 'Alokasi', 'NO_EOR': 'No EOR',
                            'CONTAINER_TYPE': 'Tipe Kontainer', 'Selisih_Harga_per_MHR': 'Keuntungan per MHR',
                            'PREDIKSI/MHR_SPIL': 'Harga/MHR SPIL', 'HargaPerMHR_Lain': 'Harga/MHR Lain',
                            'WARNING_COUNT': 'Material Tidak Dikenali'
                        }
                        format_map_detail = {
                            'Harga/MHR Final': 'Rp {:,.0f}/jam', 'MHR Final': '{:,.2f}', 'Keuntungan per MHR': 'Rp {:,.0f}',
                            'Harga/MHR SPIL': 'Rp {:,.0f}', 'Harga/MHR Lain': 'Rp {:,.0f}',
                            'Material Tidak Dikenali': '{:,.0f}'
                        }
                        sort_key_display = 'Keuntungan per MHR'
                    else: 
                        display_cols = ['NO_EOR', 'CONTAINER_TYPE', 'ALOKASI', 'HARGA_FINAL', 'MHR', 'Selisih_Prediksi_Biaya', 'PREDIKSI_SPIL', 'Prediksi_Biaya_Lain', 'WARNING_COUNT']
                        rename_map_detail = {
                            'HARGA_FINAL': 'Biaya Final', 'MHR': 'MHR Final', 'ALOKASI': 'Alokasi', 'NO_EOR': 'No EOR',
                            'CONTAINER_TYPE': 'Tipe Kontainer', 'Selisih_Prediksi_Biaya': 'Potensi Keuntungan',
                            'PREDIKSI_SPIL': 'Biaya SPIL', 'Prediksi_Biaya_Lain': 'Biaya Lain',
                            'WARNING_COUNT': 'Material Tidak Dikenali'
                        }
                        format_map_detail = {
                            'Biaya Final': 'Rp {:,.0f}', 'MHR Final': '{:,.2f}', 'Potensi Keuntungan': 'Rp {:,.0f}',
                            'Biaya SPIL': 'Rp {:,.0f}', 'Biaya Lain': 'Rp {:,.0f}',
                            'Material Tidak Dikenali': '{:,.0f}'
                        }
                        sort_key_display = 'Potensi Keuntungan'

                    display_cols_exist = [col for col in display_cols if col in final_results.columns]
                    display_df = final_results[display_cols_exist].rename(columns=rename_map_detail)
                    
                    st.dataframe(
                        display_df.sort_values(by=sort_key_display, ascending=False).style.format(format_map_detail, na_rep='-'),
                        height=600, use_container_width=True
                    )

                    sorted_display_df = display_df.sort_values(by=sort_key_display, ascending=False)

                    csv_final = sorted_display_df.to_csv(index=False).encode('utf-8')
                    st.download_button(label="Download Hasil Alokasi", data=csv_final, file_name=f"hasil_alokasi_{depo_option}.csv", mime="text/csv")
                    
                    with st.expander("Lihat Tabel Alokasi Lengkap", expanded=False):
                        st.caption("Tabel ini menampilkan hasil alokasi final dan semua detail kalkulasi.")
                        base_info_cols = ['NO_EOR', 'CONTAINER_TYPE', 'ALOKASI', 'HARGA_FINAL', 'MHR', 'Selisih_Prediksi_Biaya', 'Selisih_Harga_per_MHR', 'WARNING_COUNT']
                        pred_cols_all = sorted([col for col in final_results.columns if col.startswith("PREDIKSI_") and not col.startswith("PREDIKSI/MHR_")])
                        mhr_cols_all = sorted([col for col in final_results.columns if col.startswith("MHR_") and col != 'MHR'])
                        ratio_cols_all = sorted([col for col in final_results.columns if col.startswith("PREDIKSI/MHR_")])
                        comprehensive_cols = base_info_cols + pred_cols_all + mhr_cols_all + ratio_cols_all
                        comprehensive_cols_exist = [col for col in comprehensive_cols if col in final_results.columns]
                        detail_df_comprehensive = final_results[comprehensive_cols_exist]
                        rename_map_comprehensive = {
                            'HARGA_FINAL': 'Biaya Final', 'NO_EOR': 'No EOR', 'CONTAINER_TYPE': 'Tipe Kontainer',
                            'ALOKASI': 'Alokasi', 'Selisih_Prediksi_Biaya': 'Potensi Keuntungan (Total)',
                            'Selisih_Harga_per_MHR': 'Potensi Keuntungan (per MHR)', 'MHR': 'MHR Final',
                            'WARNING_COUNT': 'Material Tidak Dikenali'
                        }
                        format_dict_full = {
                            'Biaya Final': 'Rp {:,.0f}', 'MHR Final': '{:,.2f}',
                            'Potensi Keuntungan (Total)': 'Rp {:,.0f}', 'Potensi Keuntungan (per MHR)': 'Rp {:,.0f}/jam',
                            'Material Tidak Dikenali': '{:,.0f}'
                        }
                        for col in detail_df_comprehensive.columns:
                            if col.startswith('PREDIKSI_') and not col.startswith('PREDIKSI/MHR_'):
                                new_name = col.replace('PREDIKSI_', 'Biaya ')
                                rename_map_comprehensive[col] = new_name
                                format_dict_full[new_name] = 'Rp {:,.0f}'
                            elif col.startswith('MHR_'):
                                new_name = col.replace('MHR_', 'MHR ')
                                rename_map_comprehensive[col] = new_name
                                format_dict_full[new_name] = '{:,.2f}'
                            elif col.startswith('PREDIKSI/MHR_'):
                                new_name = col.replace('PREDIKSI/MHR_', 'Biaya/MHR ')
                                rename_map_comprehensive[col] = new_name
                                format_dict_full[new_name] = 'Rp {:,.0f}/jam'
                        display_df_renamed = detail_df_comprehensive.rename(columns=rename_map_comprehensive)
                        sort_column = 'Potensi Keuntungan (Total)'
                        if sort_column not in display_df_renamed.columns:
                            sort_column = 'No EOR'
                        sorted_df = display_df_renamed.sort_values(by=sort_column, ascending=False)
                        st.dataframe(
                            sorted_df.style.format(format_dict_full, na_rep='-'),
                            height=600,
                            use_container_width=True
                        )
                        csv_pred_detail = sorted_df.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="Download Tabel Lengkap",
                            data=csv_pred_detail,
                            file_name=f"prediksi_super_lengkap_{depo_option}.csv",
                            mime="text/csv",
                            key="download_super_lengkap"
                        )
            except Exception as e:
                st.error(f"Terjadi error: {str(e)}")
                st.exception(e)
        elif run_bulk_button:
            st.warning("Mohon unggah file CSV terlebih dahulu.")
else:
    st.warning("Pipeline kalkulasi tidak dapat dimuat. Pastikan file master tersedia dan koneksi berhasil.")
