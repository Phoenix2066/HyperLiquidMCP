# HyperLiquid FastMCP Server 🚀

This repository contains a Model Context Protocol (MCP) Server built using the FastMCP framework in Python. This server exposes functions (like getting prices or checking account balance) from the HyperLiquid Decentralized Exchange (DEX) Python SDK to be used by AI agents or clients like MCP Inspector.

## ⚙️ Setup and Installation1. Prerequisites
**You must have Python 3.10+ installed on your system**
### Clone this Repo:
```
git clone https://github.com/Phoenix2066/HyperLiquidMCP
cd .\HyperLiquidMCP
```
### Create and activate a virtual environment
To create a Python Virtual Environment:
```
python -m venv venv
```
To activate the virtual Environment:      
Windows: 
```
.\venv\bin\activate
```
Mac/Linux: 
```
source myenv/bin/activate
```
### Install Dependencies
Install the necessary Python packages:

```Bash
pip install fastmcp hyperliquid-python-sdk python-dotenv eth-account
```

### 🔐 Configuration (Authentication)
This server uses your wallet's private key to sign requests for trading actions and view private account data.
### **⚠️ Security Warning** DO NOT use the private key for your main wallet with real funds. Always use a dedicated Testnet key or a small, segregated account for automated trading and testing.

### Steps:
- Create .env file: In the root directory of this project, create a new file named .env.
- Export Key: Export the 64-character private key from your MetaMask (or other EVM wallet) testing account.
- Add Configuration: Paste the key into the .env file and set the environment flags:

```
# Replace the placeholder with your 64-character private key
HYPERLIQUID_PRIVATE_KEY="YOUR_64_CHAR_PRIVATE_KEY_HERE"
# Set to 'true' to ensure connection to the Testnet environment
HYPERLIQUID_TESTNET="true"
```
### 🔬 Running and Monitoring the Server
You can run and test the server using the fastMCP INspector:

1. Open MCP Inspector:
     ```Bash
     npx @modelcontextprotocol/inspector
     ```
   The command will launch a local server and print a URL (e.g., http://127.0.0.1:6274) to the console.   
2. Open the URL in your web browser.      
   In the Inspector UI, the connection details should be pre-filled for STDIO transport. Click Connect. Go to the Tools tab.     
3. You can now test the exposed functions directly via the tool tab.
