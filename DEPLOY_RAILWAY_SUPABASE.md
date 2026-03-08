# Steps to Move Finger Bending Analysis Tool to Railway + Supabase

This project is already set up for deployment (Dockerfile, `entrypoint.sh`, `railway.json`, `schema.sql`, `db.py`). Follow these steps to get it live.

---

## Part 1: Supabase (database for config saving)

1. **Create a Supabase project**
   - Go to [supabase.com](https://supabase.com) → Sign in → **New project**
   - Pick org, name, database password, region → **Create project**
   - Wait until the project is ready (green checkmark)

2. **Get API credentials**
   - In the project: **Project Settings** (gear) → **API**
   - Copy and save:
     - **Project URL** (e.g. `https://xxxxx.supabase.co`)
     - **anon public** key (long JWT string)

3. **Create database tables**
   - In Supabase: **SQL Editor** → **New query**
   - Open `schema.sql` in this repo, copy its **entire** contents
   - Paste into the SQL Editor → **Run**
   - You should see “Success. No rows returned” (tables and RLS policies are created)

---

## Part 2: GitHub (so Railway can deploy)

4. **Push this project to GitHub**
   - Create a **new repository** on GitHub (e.g. `Finger_Bending_Analysis_Tool`)
   - From the project folder:
     ```bash
     cd "d:\ML project1\Cursor_streamlit_Desktop\Finger_Bending_Analysis_Tool"
     git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
     git push -u origin main
     ```
   - Or: clone your repo first, copy all project files (except `.git`) into it, then commit and push.

---

## Part 3: Railway (hosting the app)

5. **Create a Railway project**
   - Go to [railway.app](https://railway.app) → Sign in
   - **New Project** → **Deploy from GitHub repo**
   - Select the repo you pushed in step 4
   - **Root Directory:** Leave **empty** (or `.`) so Railway builds from the **repo root**. This repo has `app.py`, `dl_model_tab.py`, `esn_model_tab.py`, etc. at the root. If Root Directory is set to a subfolder (e.g. `finger_analysis`) that doesn’t contain the full app, you’ll get an old build without DL/ESN tabs.

6. **Set environment variables (required for config save to work)**
   - In the Railway service → **Variables** tab → **Add Variable** (or **RAW Editor**)
   - Add these **exact** names and your real values (same as in your local `.env`):

   | Variable            | Value                          |
   |---------------------|--------------------------------|
   | `PORT`              | `8501`                         |
   | `SUPABASE_URL`      | Your Supabase Project URL (e.g. `https://xxxxx.supabase.co`) |
   | `SUPABASE_ANON_KEY` | Your Supabase **anon public** key (long JWT from Project Settings → API) |

   **Tip:** Copy the values from your local `.env` and paste them into Railway Variables. Do not commit `.env`; only set these in Railway’s UI.

7. **Get a public URL**
   - **Settings** → **Networking** → **Public Networking**
   - **Generate Domain** (or add a custom domain)
   - For the new domain, set **target port** to **8501** (same as `PORT`)

8. **Deploy**
   - Railway will build from the **Dockerfile** and run **entrypoint.sh**
   - After the build, open the generated URL (e.g. `https://xxx.up.railway.app`)
   - In deploy logs you should see: `Starting Streamlit on 0.0.0.0:8501`

---

## Part 4: Local `.env` (optional, for running locally with Supabase)

- Copy `.env.example` to `.env` (create `.env.example` if missing, with placeholders only)
- In `.env` set:
  - `SUPABASE_URL` = your Supabase Project URL
  - `SUPABASE_ANON_KEY` = your Supabase anon key
- Do **not** commit `.env` (it should be in `.gitignore`)

---

## Checklist

| Step | What |
|------|------|
| 1–3  | Supabase project created, API keys copied, `schema.sql` run in SQL Editor |
| 4    | Code pushed to a GitHub repository |
| 5    | Railway project created from that repo; Root Directory set if app is in a subfolder |
| 6    | Variables set: `PORT=8501`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` |
| 7    | Public domain generated, target port = 8501 |
| 8    | App opens at the Railway URL and config saving works (Supabase) |

---

## If the app doesn’t load or config doesn’t save

- **App not loading:** Confirm **Variables** has `PORT` = `8501` and **Networking** target port is **8501**. Redeploy and check logs for `Starting Streamlit on 0.0.0.0:8501`.
- **Config not saving:** Confirm `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set in Railway Variables and that you ran the full `schema.sql` (including RLS policies) in Supabase.

---

## Railway shows old version or missing DL / ESN tabs

1. **Use the correct repo and branch**
   - Railway → your service → **Settings** → confirm it’s connected to the repo that has the full app (e.g. `REUDE-Technologies/Finger_Bending_Analysis_Tool` or `Kandan007/Testing`) and branch **main**.

2. **Root Directory must be the app root**
   - **Settings** → **Root Directory**
   - Set to **empty** or `.` (repo root). The Dockerfile and all files (`app.py`, `dl_model_tab.py`, `esn_model_tab.py`, etc.) must be at that path. If you had a subfolder like `finger_analysis` before, clear it so the root is used.

3. **Trigger a fresh deploy**
   - **Deployments** → open the latest deployment → **Redeploy** (or push a small commit to `main`).
   - If available, use **“Clear build cache”** or **“Redeploy from scratch”** so the image is rebuilt from the current repo.

4. **Check build logs**
   - In the build log you should see `COPY . .` copying the repo and `pip install -r requirements.txt` including `torch`, `scikit-learn`, `plotly`. If the build fails on `torch` (e.g. out of memory), the DL tab will show “requires PyTorch”; consider increasing Railway plan or using a CPU-only torch wheel.
