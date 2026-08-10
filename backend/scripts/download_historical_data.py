
"""
Download historical match data from football-data.co.uk
"""

import requests
from pathlib import Path

def download_historical_data():
    """
    Download CSV files from football-data.co.uk
    """
    base_url = "https://www.football-data.co.uk/mmz4281"
    
    leagues = {
        'epl': 'E0',         # Premier League
        'championship': 'E1', # Championship
        'laliga': 'SP1',     # La Liga
        'bundesliga': 'D1',  # Bundesliga
        'seriea': 'I1',      # Serie A
        'ligue1': 'F1',      # Ligue 1
        'eredivisie': 'N1',  # Eredivisie
    }
    
    # Seasons to download (last 7 years)
    seasons = ['1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425']
    
    data_dir = Path('data/historical')
    data_dir.mkdir(parents=True, exist_ok=True)
    
    total_downloaded = 0
    
    for league_name, league_code in leagues.items():
        league_dir = data_dir / league_name
        league_dir.mkdir(exist_ok=True)
        
        print(f"\n📥 Downloading {league_name.upper()} data...")
        
        for season in seasons:
            url = f"{base_url}/{season}/{league_code}.csv"
            filename = league_dir / f"{season}.csv"
            
            if filename.exists():
                print(f"  ⏭️  Skipping {season} (already exists)")
                continue
            
            try:
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    print(f"  ✅ Downloaded {season}")
                    total_downloaded += 1
                else:
                    print(f"  ❌ Failed {season} (status {response.status_code})")
            except Exception as e:
                print(f"  ❌ Error {season}: {e}")
    
    print(f"\n✅ Downloaded {total_downloaded} files")
    print(f"📁 Data saved to: {data_dir.absolute()}")

if __name__ == "__main__":
    download_historical_data()