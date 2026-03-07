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
   - If the app lives in a **subfolder** (e.g. only `Finger_Bending_Analysis_Tool` is the app):
     - Click the new service → **Settings** → **Root Directory** → set to that subfolder (e.g. `Finger_Bending_Analysis_Tool`)

6. **Set environment variables**
   - In the Railway service → **Variables** tab → **Add Variable** (or **RAW Editor**)
   - Add:

   | Variable            | Value                          |
   |---------------------|--------------------------------|
   | `PORT`              | `8501`                         |
   | `SUPABASE_URL`      | Your Supabase Project URL      |
   | `SUPABASE_ANON_KEY` | Your Supabase anon public key  |

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
