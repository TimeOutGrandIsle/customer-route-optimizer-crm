# 🚚 Customer Route Optimizer

A powerful Streamlit app that finds the most efficient route for visiting all customers using real driving distances.

## ✨ Features

- Upload addresses from Excel
- Automatic geocoding
- Real driving times via OSRM
- **30 minutes on-site** per customer
- Global Day Start & End Time
- OR-Tools optimization (50+ stops)
- Interactive map + Google Maps export

## 📋 Excel Format (Simple)

| Customer Name | Address                          |
|---------------|----------------------------------|
| John Doe      | 123 Main St, Jackson, MS 39201   |
| Jane Smith    | 456 Oak Ave, Ridgeland, MS 39157 |

Only the **Address** column is required.

## 🛠️ Installation & Run

```bash
git clone https://github.com/YOURUSERNAME/customer-route-optimizer.git
cd customer-route-optimizer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py