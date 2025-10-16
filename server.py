import os
import sys
from typing import Dict, Any
from eth_account import Account
from dotenv import load_dotenv

# FastMCP imports
from fastmcp import FastMCP

# HyperLiquid SDK imports
# Assuming the latest version uses these standard names
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange

# --- 1. INITIALIZATION AND AUTHENTICATION ---

load_dotenv()

# Get the private key from your .env file
private_key = os.environ.get("HYPERLIQUID_PRIVATE_KEY")

is_key_valid = True
hl_account = None
user_address = "0x000000000000000000000000000000000000DEAD" # Default address

if not private_key:
    is_key_valid = False
    print("WARNING: HYPERLIQUID_PRIVATE_KEY not set. Trading tools disabled.", file=sys.stderr)
else:
    try:
        # Step 1: Use eth_account to validate and create the account object
        # The key must be a 32-byte (64-character) hex string.
        # We replace '0x' if present to ensure proper handling by the library.
        key_bytes = private_key.lower().replace('0x', '')
        hl_account = Account.from_key(key_bytes)
        user_address = hl_account.address
        
    except ValueError as e:
        is_key_valid = False
        # Catches the '32 bytes long, instead of X bytes' error
        print(f"ERROR: Invalid Private Key format in .env: {e}", file=sys.stderr)
    except Exception as e:
        is_key_valid = False
        print(f"An unexpected error occurred during key setup: {e}", file=sys.stderr)


# Client Setup (Info client is always safe)
hl_info = Info() 

# Client Setup (Exchange client - only initialize if key is valid)
if is_key_valid:
    # FINAL FIX: Pass the hl_account object as the FIRST POSITIONAL argument.
    # This bypasses the keyword argument issue.
    try:
        hl_exchange = Exchange(hl_account)
    except TypeError as e:
        # If the SDK is extremely outdated or unusual, this will catch it.
        hl_exchange = None
        print(f"CRITICAL ERROR: Failed to initialize Exchange client: {e}", file=sys.stderr)
        is_key_valid = False
else:
    hl_exchange = None


# --- 2. FASTMCP SERVER DEFINITION ---

mcp = FastMCP(
    name="HyperLiquid DEX Tester",
    instructions="Provides read-only market data and authorized trading tools for HyperLiquid DEX."
)

@mcp.tool()
async def get_user_state() -> Dict[str, Any]:
    """
    Retrieves the user's current account state (balances, margin, and positions) 
    for the configured wallet address.
    """
    if not is_key_valid:
        return {"error": "Private key is invalid or missing. Trading tools are disabled."}
        
    # Use the Info client (read-only) to query the account state
    state = hl_info.user_state(user_address)
    return state

@mcp.tool()
async def get_mid_price(coin: str) -> float:
    """
    Retrieves the current mid-price (midpoint between best bid and best ask) for a perpetual market.
    Args: coin (str): The asset symbol (e.g., 'BTC', 'ETH', 'SOL').
    """
    
    # Fetch data from HyperLiquid SDK. This now returns a DICTIONARY.
    mids_dict = hl_info.all_mids()
    
    # CRITICAL CHECK: Ensure the response is a dictionary
    if not isinstance(mids_dict, dict):
        print(f"ERROR: HyperLiquid API returned unexpected type: {type(mids_dict)}. Response: {mids_dict}", file=sys.stderr)
        return -1.0 
    
    # 1. Standardize the coin symbol to match the dictionary keys
    coin_symbol = coin.upper()
    
    # 2. Look up the price using the coin symbol as the key
    price_str = mids_dict.get(coin_symbol)
    
    if price_str is None:
        # Coin not found in the dictionary
        return 0.0
    
    # 3. Convert the string price to a float and return it
    try:
        return float(price_str)
    except (ValueError, TypeError) as e:
        print(f"WARNING: Could not convert price '{price_str}' to float for {coin_symbol}. Error: {e}", file=sys.stderr)
        return -2.0 # Indicates a conversion failure

# --- 3. RUN THE SERVER ---
if __name__ == "__main__":
    # Ensure all print statements go to stderr so they don't corrupt the MCP messages on stdout
    print(f"Starting HyperLiquid MCP Server for address: {user_address}. Waiting for client connection (STDIO)...", file=sys.stderr)
    mcp.run()