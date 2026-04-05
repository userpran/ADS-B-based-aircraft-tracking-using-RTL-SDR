import pandas as pd
import pymap3d as pm
import datetime

# Load your CPR-decoded data
df = pd.read_csv("~/projects/ADS-B-based-aircraft-tracking-using-RTL-SDR/src/output/20260203/output1003.csv")

# Convert altitude ft → meters
df['alt_m'] = df['alt'] * 0.3048

# Your antenna / receiver location
gs_lat = 8.5000
gs_lon = 76.9000
gs_alt = 10  # meters (change to actual station height)

# Compute azimuth/elevation for each row
def compute_aer(row):
    az, el, slant = pm.geodetic2aer(
        row['lat'], row['lon'], row['alt_m'],
        gs_lat, gs_lon, gs_alt
    )
    return pd.Series({'azimuth': az, 'elevation': el, 'slant_range': slant})

df = df.dropna(subset=['lat','lon','alt'])
df = df[(df['lat'] != 0) & (df['lon'] != 0)]
df[['azimuth', 'elevation', 'slant_range']] = df.apply(compute_aer, axis=1)

timestamp = datetime.datetime.now().strftime("%m%d_%H%M")
output_filename = f"~/projects/ADS-B-based-aircraft-tracking-using-RTL-SDR/azel/azel_{timestamp}.csv"

# Save updated CSV
df.to_csv(output_filename, index=False)

df.head()
