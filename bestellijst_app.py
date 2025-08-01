import streamlit as st
import pandas as pd
from collections import defaultdict, Counter
from io import BytesIO

st.set_page_config(page_title="BOM Bestellijst Tool", layout="wide")

st.title("BOM Generator")
st.write("Upload een BOM CSV-bestand met (#) als scheidingsteken.")

uploaded_file = st.file_uploader("Kies een BOM-bestand", type=["csv"])

if uploaded_file is not None:
    try:
        df_raw = pd.read_csv(uploaded_file, sep=r'\(#\)', engine='python', encoding='ISO-8859-1')
        df_raw.columns = df_raw.columns.str.strip().str.lower().str.replace(r'[^\w]', '', regex=True)

        df = df_raw.rename(columns={
            'parentpart': 'parentpart',
            'qtyper': 'qtyper',
            'item': 'item',
            'template': 'template',
            'makebuy': 'makebuy',
            'linetype': 'linetype',
            'productname': 'productname',
            'level': 'level'
        })

        df['qtyper'] = df['qtyper'].astype(str).str.replace(',', '.').astype(float)

        def classify(row):
            makebuy = str(row.get('makebuy', '')).strip().lower()
            linetype = str(row.get('linetype', '')).strip().lower()
            if 'purch' in makebuy:
                return 'buy'
            elif 'production' in makebuy:
                if 'phantom' in makebuy or 'phantom' in linetype:
                    return 'phantom'
                else:
                    return 'make'
            return 'unknown'

        df['type'] = df.apply(classify, axis=1)

        def is_length_item(row):
            return 'mm' in str(row.get('template', '')).lower()

        root_rows = df[df['level'] == 0]
        if root_rows.empty:
            st.error("Geen root item gevonden (level == 0 ontbreekt).")
            st.stop()
        root_item = root_rows['item'].iloc[0]

        trace_log = defaultdict(list)
        length_log = defaultdict(list)
        seen_paths = set()

        def traverse(item, multiplier=1, path=[]):
            matches = df[df['parentpart'] == item]
            if matches.empty:
                return

            for _, row in matches.iterrows():
                child = row['item']
                qty = float(row['qtyper'])
                type_ = row['type']
                is_length = is_length_item(row)
                new_path = path + [(item, qty)]

                path_key = tuple(new_path + [(child, qty)])
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)

                total_qty = multiplier * qty

                if type_ in ['buy', 'make']:
                    trace_log[child].append((total_qty, new_path + [(child, qty)]))
                    if is_length:
                        length_log[child].append((total_qty, new_path + [(child, qty)]))
                    else:
                        final_results[child] += total_qty
                elif type_ == 'phantom':
                    traverse(child, total_qty, new_path)

        final_results = Counter()
        traverse(root_item, 1, [])

        result_df = pd.DataFrame(final_results.items(), columns=['item', 'total_quantity'])
        result_df = result_df.merge(df[['item', 'productname']].drop_duplicates(), on='item', how='left')
        result_df = result_df.groupby(['item', 'productname'], as_index=False)['total_quantity'].sum()
        result_df = result_df.sort_values(by='item')

        st.success("✅ Bestellijst gegenereerd")
        st.dataframe(result_df, use_container_width=True)

        st.subheader("🔍 Traceer herkomst per artikel")
        trace_item = st.selectbox("Kies een itemnummer om het berekeningspad te zien:", sorted(trace_log.keys()))
        if trace_item:
            for idx, (qty, path) in enumerate(trace_log[trace_item], 1):
                st.markdown(f"**Pad {idx}: totaal {qty} stuks**")
                path_str = " → ".join([f"{i} (×{q})" for i, q in path])
                st.code(path_str)

        # Tabel met lengte-artikelen onder traceerfunctie
        st.subheader("📏 Lengte-artikelen")
        length_items = []
        for item, logs in length_log.items():
            total_mm = sum(qty for qty, _ in logs)
            name = df[df['item'] == item]['productname'].dropna().unique()
            desc = name[0] if len(name) else ''
            length_items.append({"item": item, "productname": desc, "total_mm": total_mm})

        length_df = pd.DataFrame(length_items)
        st.dataframe(length_df, use_container_width=True)

        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Bestellijst')
            length_df.to_excel(writer, index=False, sheet_name='Lengte-artikelen')

        st.download_button(
            label="📥 Download Excel-bestand",
            data=output.getvalue(),
            file_name="bestellijst.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"Er ging iets mis: {e}")
