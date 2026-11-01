# Run the app on this machine against the Chroma stores in chromadb/.
#
# One-time setup:
#   python -m venv .venv
#   .\.venv\Scripts\pip install --index-url https://download.pytorch.org/whl/cpu torch
#   .\.venv\Scripts\pip install -r requirements-local.txt
#   az login            # needs read access to the kv-legalai-m4 Key Vault
#
# Then:  .\run_local.ps1

$env:LEGAL_AI_LOCAL = "1"
# The watcher walks every loaded module, including transformers' lazy vision
# models (which need torchvision), and floods the console. Restart to reload.
$env:STREAMLIT_SERVER_FILE_WATCHER_TYPE = "none"

$secrets = @{
    "groq-api-key"          = "GROQ_API_KEY"
    "courtlistener-api-key" = "COURTLISTENER_API_KEY"
    "apify-token"           = "APIFY_TOKEN"
    "regulations-api-key"   = "REGULATIONS_API_KEY"
}
foreach ($name in $secrets.Keys) {
    $var = $secrets[$name]
    if (Test-Path "env:$var") { continue }
    $value = az keyvault secret show --vault-name kv-legalai-m4 --name $name --query value -o tsv 2>$null
    if ($value) { Set-Item "env:$var" $value } else { Write-Warning "Could not read $name from Key Vault" }
}

& "$PSScriptRoot\.venv\Scripts\streamlit.exe" run "$PSScriptRoot\streamlit_app.py" @args
