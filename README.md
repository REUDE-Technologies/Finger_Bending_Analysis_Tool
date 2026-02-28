# Finger Bending Analysis Tool

Professional data extraction and compilation tool for soft robotic finger bending measurements. Processes point tracking data at various pressure levels and computes displacement, bending angles, and statistics.

---

## Deploy to Railway + Supabase

### 1. Set up Supabase

1. Go to [supabase.com](https://supabase.com) → create account → **New Project**
2. Wait for the project to be ready, then go to **Project Settings → API**
3. Copy:
   - **Project URL** (e.g. `https://xxxxx.supabase.co`)
   - **anon public** key
4. Open **SQL Editor** → New query → paste the full contents of `schema.sql` → Run

### 2. Deploy to Railway

1. Push this project to a **GitHub** repository
2. Go to [railway.app](https://railway.app) → **Start a New Project** → **Deploy from GitHub repo**
3. Select your repository. If `finger_analysis` is in a subfolder, set **Root Directory** to `finger_analysis` in Settings
4. In the project, click your service → **Variables** tab → add:

   | Variable           | Value                    |
   |--------------------|--------------------------|
   | `SUPABASE_URL`     | Your Supabase Project URL |
   | `SUPABASE_ANON_KEY`| Your Supabase anon key   |

5. Go to **Settings** → **Networking** → **Generate Domain** to get your public URL
6. Railway will build and deploy automatically

---

## Prerequisites (local)

- **Python 3.10+**
- **pip** (Python package manager)

---

## Quick Start (local)

### 1. Create a virtual environment (recommended)

```bash
cd finger_analysis
python -m venv venv
```

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
venv\Scripts\activate.bat
```

**macOS/Linux:**
```bash
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the app

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

---

## Optional: Supabase (config saving)

The app can save and load test configurations (finger types, materials, etc.) if Supabase is configured. Without it, the app works fully but configs won't be persisted.

### 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) and create a free account.
2. Create a new project.
3. Go to **Project Settings → API** and copy:
   - **Project URL**
   - **anon public** key

### 2. Create database tables

In the Supabase **SQL Editor**, run the contents of `schema.sql`:

```sql
-- Copy and paste the full contents of schema.sql
```

### 3. Configure environment

Create a `.env` file in the `finger_analysis` folder:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
```

---

## File format

Point tracking files should have **t, x, y** columns (time, x-coordinate, y-coordinate):

- **ZIP upload:** Upload a ZIP containing `.txt` files (e.g. `p1.txt`, `p2.txt`, …).
- **TXT upload:** Upload individual `.txt` files.

Each file can have optional header rows (e.g. `p1`, `t x y`); they are skipped automatically.

---

## Usage

1. **Test Configuration** — Enter finger type, materials, speed, etc.
2. **Select pressure levels** — Choose which kPa levels you have data for (e.g. 10, 20, 30).
3. **Upload files** — For each pressure level, upload ZIP or TXT point data.
4. **Process & Compile** — Click to process and view results.
5. **Export** — Download the compiled Excel from the Export tab.

---

## Project structure

```
finger_analysis/
├── app.py               # Streamlit UI
├── processing.py        # Data parsing, displacement, angles
├── db.py                # Supabase config storage
├── schema.sql           # Database schema (Supabase)
├── Dockerfile           # Docker build for Railway
├── railway.json         # Railway deployment config
├── .python-version      # Python 3.11 for Railway
├── .env.example         # Env var template
├── requirements.txt
├── .streamlit/
│   └── config.toml      # Streamlit theme
├── FORMULAS.md          # Mathematical formulas used
└── README.md            # This file
```
