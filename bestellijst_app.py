import streamlit as st
import pandas as pd
from collections import Counter, defaultdict
from io import BytesIO

st.set_page_config(page_title="BOM-Tool per Root-productie (Definitieve versie)", layout="wide")

try:
    st.title("BOM-Tool per Root-productie (zonder dubbele paden, met lengte-artikelen)")
    st.write("Upload een BOM CSV-bestand met (#) als scheidingsteken.")

    uploaded_file = st.file_uploader("Kies een BOM-bestand", type=["csv"])

    if uploaded_file is not None:
        df_raw = pd.read_csv(uploaded_file, sep=r'\(#\)', engine='python', encoding='ISO-8859-1')
        df_raw.columns = df_raw.columns.str.strip().str.lower()
        df = df_raw.rename(columns={
            'parentpart': 'parentpart',
            'qtyper': 'qtyper',
            'item': 'item',
            'template': 'template',
            'makebuy': 'makebuy',
            'linetype': 'linetype',
            'name': 'name',
            'level': 'level'
        })

        df['qtyper'] = df['qtyper'].astype(str).str.replace(',', '.').astype(float)

        root_rows = df[df['level'] == 0]
        root_item = root_rows['item'].iloc[0]

        trace_log = defaultdict(list)
        length_log = defaultdict(list)

        def is_length_item(row):
            return 'mm' in str(row.get('template', '')).lower()

        def bereken_aantal(item, multiplier=1, path=[]):
            matches = df[df['parentpart'] == item]
            if matches.empty:
                return [(multiplier, path + [item])]

            resultaten = []
            for _, row in matches.iterrows():
                child = row['item']
                qty = float(row['qtyper'])
                resultaten.extend(bereken_aantal(child, multiplier * qty, path + [item]))
                if is_length_item(row):
                    length_log[child].append((multiplier * qty, path + [item, child]))
            return resultaten

        paden = bereken_aantal(root_item)

        final_results = Counter()
        for aantal, pad in paden:
            final_results[pad[-1]] += aantal
            trace_log[pad[-1]].append((aantal, pad))

        result_df = pd.DataFrame(final_results.items(), columns=['item', 'total_quantity'])
        result_df = result_df.merge(df[['item', 'name']].drop_duplicates(), on='item', how='left')
        result_df = result_df.groupby(['item', 'name'], as_index=False)['total_quantity'].sum()
        result_df = result_df.sort_values(by='item')

        st.success("✅ Bestellijst per root-productie gegenereerd")
        st.dataframe(result_df, use_container_width=True)

        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Bestellijst')
            length_items = []
            for item, logs in length_log.items():
                total_mm = sum(qty for qty, _ in logs)
                description = df[df['item'] == item]['name'].dropna().unique()
                desc = description[0] if len(description) else ''
                length_items.append({"item": item, "name": desc, "total_mm": total_mm})
            length_df = pd.DataFrame(length_items)[['item', 'name', 'total_mm']]
            length_df.to_excel(writer, index=False, sheet_name='Lengte-artikelen')

        st.download_button(
            label="📥 Download Excel-bestand",
            data=output.getvalue(),
            file_name="bestellijst.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.subheader("Traceer herkomst per artikel")
        trace_item = st.selectbox("Kies een itemnummer om het berekeningspad te zien:", sorted(trace_log.keys()))
        if trace_item:
            for idx, entry in enumerate(trace_log[trace_item], 1):
                if isinstance(entry, tuple) and len(entry) >= 2:
                    qty, path = entry[:2]
                    st.markdown(f"**Pad {idx}: totaal {qty} stuks per root-productie**")
                    path_str = " → ".join([f"{i}" for i in path])
                    st.code(path_str)
                else:
                    st.error(f"Onverwachte inhoud in trace_log: {entry}")

        st.subheader("📏 Lengte-artikelen (in mm, totaal opgeteld)")
        st.dataframe(length_df)

except Exception as e:
    st.error(f"Er ging iets mis: {e}")
