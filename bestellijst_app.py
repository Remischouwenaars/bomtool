import streamlit as st
import pandas as pd
from collections import defaultdict, Counter
from io import BytesIO

st.set_page_config(page_title="BOM-Tool", layout="wide")

def safe_convert(x):
    try:
        return str(int(float(x)))
    except:
        return None

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

def is_length_item(row):
    template = str(row.get('template', '')).lower()
    return 'mm' in template

def traverse(item_id, multiplier, bom, children_map, path, trace_log, length_log):
    results = Counter()
    matches = bom[bom['item'] == str(item_id)]
    for _, row in matches.iterrows():
        item = row['item']
        qty = row.get('qtyper', 1)
        type_ = row['type']
        is_length = is_length_item(row)
        qty = float(qty) if pd.notna(qty) else 1
        total_qty = multiplier * qty

        new_path = path + [(item, qty)]

        if type_ == 'buy':
            if is_length:
                length_log[item].append((qty, list(new_path)))
            else:
                results[item] += total_qty
                trace_log[item].append((total_qty, list(new_path)))
            return results
        elif type_ == 'make':
            if is_length:
                length_log[item].append((qty, list(new_path)))
            else:
                results[item] += total_qty
                trace_log[item].append((total_qty, list(new_path)))
            return results
        elif type_ == 'phantom':
            for child_row in children_map.get(item, []):
                results += traverse(child_row['item'], total_qty, bom, children_map, new_path, trace_log, length_log)
    return results

st.title("BOM-Tool")
st.write("Upload een BOM CSV-bestand met (#) als scheidingsteken.")

uploaded_file = st.file_uploader("Kies een BOM-bestand", type=["csv"])

if uploaded_file is not None:
    try:
        df_raw = pd.read_csv(uploaded_file, sep=r'\(#\)', engine='python', encoding='ISO-8859-1')

        # Normaliseer kolomnamen
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

        df['item'] = df['item'].apply(safe_convert)
        df['parentpart'] = df['parentpart'].apply(safe_convert)
        df['qtyper'] = df['qtyper'].astype(str).str.replace(',', '.').astype(float)
        df['type'] = df.apply(classify, axis=1)

        # Zoek root item op basis van Level == 0
        root_items = df[df['level'] == 0]['item'].unique()
        if len(root_items) == 0:
            st.error("Geen root item gevonden (Level == 0 ontbreekt).")
            st.stop()
        root_item = root_items[0]

        children_map = defaultdict(list)
        for _, row in df.iterrows():
            parent = row['parentpart']
            child = row['item']
            if parent and child:
                children_map[parent].append(row)

        from collections import defaultdict as dd
        trace_log = dd(list)
        length_log = dd(list)

        final_results = Counter()
        for row in children_map.get(root_item, []):
            qty = float(row.get('qtyper', 1)) if pd.notna(row.get('qtyper')) else 1
            final_results += traverse(row['item'], qty, df, children_map, [], trace_log, length_log)

        result_df = pd.DataFrame(final_results.items(), columns=['item', 'total_quantity'])
        result_df = result_df.merge(df[['item', 'name']].drop_duplicates(), on='item', how='left')
        result_df = result_df.groupby(['item', 'name'], as_index=False)['total_quantity'].sum()
        result_df = result_df.sort_values(by='item')

        st.success("Bestellijst gegenereerd (excl. lengte-artikelen)")

        for _, row in result_df.iterrows():
            if row['total_quantity'] > 10000:
                st.warning(f"⚠️ Artikel {row['item']} ({row['name']}) heeft een hoge hoeveelheid: {row['total_quantity']:.0f}")

        st.dataframe(result_df, use_container_width=True)

        st.subheader("Traceer herkomst per artikel")
        trace_item = st.selectbox("Kies een itemnummer om het berekeningspad te zien:", sorted(trace_log.keys()))

        if trace_item:
            for idx, (qty, path) in enumerate(trace_log[trace_item], 1):
                st.markdown(f"**Pad {idx}: totaal {qty} stuks**")
                path_str = " → ".join([f"{i} (×{q})" for i, q in path])
                st.code(path_str)

        # Export naar Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Bestellijst')

            # Voeg lengte-artikelen toe als tweede tab
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

        # Tabelweergave van lengte-items
        st.subheader("📏 Lengte-artikelen (in mm, totaal opgeteld)")
        st.dataframe(length_df)

    except Exception as e:
        st.error(f"Er ging iets mis: {e}")
