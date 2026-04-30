# Commands to Remove Sensitive Data from Git History

## WARNING: Read Before Running!
- These commands will rewrite Git history
- After force push, ALL collaborators must re-clone the repository
- Create a backup first: `Copy-Item -Path "c:/Users/ASUS/OneDrive/Desktop/garage" -Destination "c:/Users/ASUS/OneDrive/Desktop/garage-backup" -Recurse`

---

## Step 1: Backup Repository (IMPORTANT!)
```powershell
# Create a backup copy FIRST
Copy-Item -Path "c:/Users/ASUS\OneDrive\Desktop\garage" -Destination "c:\Users\ASUS\OneDrive\Desktop\garage-backup" -Recurse
```

---

## Step 2: Remove "Customer Sheet" from ALL Git History
```powershell
cd c:/Users/ASUS/OneDrive/Desktop/garage

# Install git-filter-repo if not already installed
pip install git-filter-repo

# Remove the folder from entire history
git filter-repo --path "Customer Sheet/" --invert-paths --force
```

---

## Step 3: Force Push to GitHub
```powershell
cd c:/Users/ASUS/OneDrive/Desktop/garage

# Force push to overwrite remote history
git push origin main --force --set-upstream
```

---

## Step 4: Verification Commands
```powershell
# Verify folder is removed from history (should return nothing)
git log --all --oneline | ForEach-Object { 
    git ls-tree -r --name-only $_.Split(" ")[0] 
} | Select-String -Pattern "Customer Sheet"

# Try to access the file (should fail)
git show origin/main:Customer Sheet/customers_raw.csv
```

---

## What Happens After Force Push
1. Remote repository is rewritten WITHOUT the sensitive folder in ANY commit
2. Old commits become "orphaned" (unreachable)
3. GitHub will garbage collect them (usually within 90 days)
4. All collaborators must `git clone` fresh (cannot pull)

---

## Risks & Warnings
- **All collaborators must re-clone** - share this with your team first!
- **Backup first** - before running filter-repo
- If anyone has the old URL, they can still access old commits until GC runs
- Consider invalidating any tokens/passwords that were in the CSV
