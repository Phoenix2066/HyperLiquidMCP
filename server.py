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

#--- Get details from the users's provided wallet ---
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

#--- Get the current mid price of the coin input.
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

# --- Get the L2 Order Book Depth (WORKAROUND using all_mids) ---
@mcp.tool()
async def get_order_book(coin: str) -> Dict[str, Any]:
    """
    [WORKAROUND] Retrieves the current price from the all_mids endpoint 
    as a simplified order book representation. Use this if the full L2 method fails.
    Args: coin (str): The asset symbol (e.g., 'BTC', 'ETH').
    """
    try:
        mids_dict = hl_info.all_mids()
        coin_symbol = coin.upper()
        price_str = mids_dict.get(coin_symbol)
        
        if price_str is None:
            return {"error": f"Coin {coin_symbol} not found in current market data."}
        
        price = float(price_str)
        
        # Create a simplified 'L2' response using the mid-price
        return {
            "coin": coin_symbol,
            "mid_price": price,
            "bids": [{"price": price * 0.9999, "size": 1.0}], # Fake bid slightly below price
            "asks": [{"price": price * 1.0001, "size": 1.0}], # Fake ask slightly above price
            "note": "⚠️ Data is simplified. Full L2 depth is unavailable in this SDK version or client.",
        }
    except Exception as e:
        print(f"ERROR in fallback order book: {e}", file=sys.stderr)
        return {"error": f"Failed to retrieve price data for {coin}: {str(e)}"}# Pydantic model for order input is optional here but highly recommended for clear tool schema
from pydantic import BaseModel, Field
from typing import Literal

class MarketOrderInput(BaseModel):
    """Defines input parameters for placing a market order."""
    coin: str = Field(..., description="The asset symbol to trade (e.g., 'BTC', 'ETH').")
    is_buy: bool = Field(..., description="True for a BUY order (go long/reduce short), False for a SELL order (go short/reduce long).")
    size: float = Field(..., gt=0, description="The size of the order, must be greater than zero.")
    reduce_only: bool = Field(False, description="Set to True to ensure the order only reduces an existing position.")


# --- Place a Market Order ---
@mcp.tool()
async def place_market_order(order: MarketOrderInput) -> Dict[str, Any]:
    """
    Executes an immediate market order to buy or sell a specified size of an asset.
    This tool requires a valid private key for transaction signing.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}

    try:
        # Get the market price for the order type
        mid_price = await get_mid_price(order.coin)
        if mid_price <= 0:
            return {"error": "Could not retrieve valid market price to use for the order."}
            
        # Place the order using the Exchange client
        result = hl_exchange.order(
            coin=order.coin.upper(),
            is_buy=order.is_buy,
            sz=order.size,
            # For market orders, limit_px is set far from the mid price to guarantee a fill
            limit_px=mid_price * (1.05 if order.is_buy else 0.95), 
            order_type={"market": True}, 
            reduce_only=order.reduce_only
        )
        
        # HyperLiquid API returns the status and hash inside the 'response' dict
        status_data = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
        
        if 'error' in status_data:
             return {"status": "failed", "exchange_error": status_data['error']}

        return {
            "status": "success",
            "message": f"Market order placed on {order.coin}.",
            "side": "BUY" if order.is_buy else "SELL",
            "size": order.size,
            "tx_hash": result.get('response', {}).get('hash')
        }

    except Exception as e:
        print(f"CRITICAL ERROR during market order placement: {e}", file=sys.stderr)
        return {"error": f"Failed to place order: {str(e)}"}
    
# --- Cancel All Open Orders ---
@mcp.tool()
async def cancel_all_orders() -> Dict[str, Any]:
    """
    Cancels all open limit and trigger orders on the user's account across all assets.
    This tool is used for risk management and requires authorization.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}
    
    try:
        # The HyperLiquid SDK method for bulk cancellation
        result = hl_exchange.cancel_all()

        # HyperLiquid returns the transaction hash for the cancellation
        tx_hash = result.get('response', {}).get('hash')
        
        if tx_hash:
            return {
                "status": "success",
                "message": "All open orders successfully submitted for cancellation.",
                "tx_hash": tx_hash
            }
        else:
             # Handle cases where the API returns success but no hash (e.g., no orders to cancel)
            return {
                "status": "warning",
                "message": "Cancellation request submitted, but no immediate transaction hash was returned (may mean no open orders found)."
            }

    except Exception as e:
        print(f"CRITICAL ERROR during cancel_all: {e}", file=sys.stderr)
        return {"error": f"Failed to execute cancel_all: {str(e)}"}
    

# --- 3. RUN THE SERVER ---
if __name__ == "__main__":
    # Ensure all print statements go to stderr so they don't corrupt the MCP messages on stdout
    print(f"Starting HyperLiquid MCP Server for address: {user_address}. Waiting for client connection (STDIO)...", file=sys.stderr)
    mcp.run()
