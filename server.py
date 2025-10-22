import os
import sys
from typing import Dict, Any, Literal
from eth_account import Account
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import json 

# FastMCP imports
from fastmcp import FastMCP

# HyperLiquid SDK imports
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants # Provides TESTNET_API_URL and MAINNET_API_URL

# -------------------- 1. INITIALIZATION AND AUTHENTICATION --------------------

load_dotenv()

# --- FIX: DETERMINE THE API ENDPOINT (Defaults to TESTNET) ---
hl_env = os.environ.get("HYPERLIQUID_ENV", "TESTNET").upper() 
HL_API_URL = constants.TESTNET_API_URL if hl_env == "TESTNET" else constants.MAINNET_API_URL

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
        key_bytes = private_key.lower().replace('0x', '')
        hl_account = Account.from_key(key_bytes)
        user_address = hl_account.address # This is the address that holds the funds
        
    except ValueError as e:
        is_key_valid = False
        print(f"ERROR: Invalid Private Key format in .env: {e}", file=sys.stderr)
    except Exception as e:
        is_key_valid = False
        print(f"An unexpected error occurred during key setup: {e}", file=sys.stderr)


# Client Setup (Info client)
# FIX APPLIED: Pass the determined API URL (Testnet or Mainnet)
hl_info = Info(HL_API_URL) 

# Client Setup (Exchange client - only initialize if key is valid)
if is_key_valid:
    try:
        # FIX APPLIED: Pass the hl_account object AND the determined API URL
        hl_exchange = Exchange(hl_account, HL_API_URL) 
    except TypeError as e:
        hl_exchange = None
        print(f"CRITICAL ERROR: Failed to initialize Exchange client: {e}", file=sys.stderr)
        is_key_valid = False
else:
    hl_exchange = None


# -------------------- 2. PYDANTIC MODELS FOR TOOL INPUTS (Documentation only) --------------------

class MarketOrderInput(BaseModel):
    """Defines input parameters for placing a market order."""
    coin: str 
    is_buy: bool 
    size: float 
    reduce_only: bool

class LimitOrderInput(BaseModel):
    """Defines input parameters for placing a limit order."""
    coin: str
    is_buy: bool
    size: float
    limit_price: float
    time_in_force: Literal["Gtc", "Ioc", "Alo"]
    reduce_only: bool

class CancelOrderInput(BaseModel):
    """Defines input parameters for canceling a specific order."""
    coin: str 
    order_id: int 
    
class CandlestickInput(BaseModel):
    """Defines input parameters for retrieving candlestick data."""
    coin: str
    interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    limit: int


# -------------------- 3. FASTMCP SERVER DEFINITION --------------------

mcp = FastMCP(
    name="HyperLiquid DEX Tester",
    instructions="Provides read-only market data and authorized trading tools for HyperLiquid DEX."
)

# -------------------- READ-ONLY TOOLS (INFO CLIENT) --------------------

@mcp.tool()
async def get_user_state() -> Dict[str, Any]:
    """
    Retrieves the user's current account state (balances, margin, and positions) 
    for the configured wallet address on the Hyperliquid trading layer.
    """
    state = hl_info.user_state(user_address)
    return state

@mcp.tool()
async def get_mid_price(coin: str) -> float:
    """
    Retrieves the current mid-price (midpoint between best bid and best ask) for a perpetual market.
    Args: coin (str): The asset symbol (e.g., 'BTC', 'ETH', 'SOL').
    """
    mids_dict = hl_info.all_mids()
    
    if not isinstance(mids_dict, dict):
        print(f"ERROR: HyperLiquid API returned unexpected type: {type(mids_dict)}. Response: {mids_dict}", file=sys.stderr)
        return -1.0 
    
    coin_symbol = coin.upper()
    price_str = mids_dict.get(coin_symbol)
    
    if price_str is None:
        return 0.0
    
    try:
        return float(price_str)
    except (ValueError, TypeError) as e:
        print(f"WARNING: Could not convert price '{price_str}' to float for {coin_symbol}. Error: {e}", file=sys.stderr)
        return -2.0 

@mcp.tool()
async def get_order_book(coin: str) -> Dict[str, Any]:
    """
    Retrieves the current price from the all_mids endpoint as a simplified order book representation.
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
            "bids": [{"price": price * 0.9999, "size": 1.0}], 
            "asks": [{"price": price * 1.0001, "size": 1.0}], 
            "note": "⚠️ Data is simplified. Full L2 depth is unavailable in this SDK version or client.",
        }
    except Exception as e:
        print(f"ERROR in fallback order book: {e}", file=sys.stderr)
        return {"error": f"Failed to retrieve price data for {coin}: {str(e)}"}

@mcp.tool()
async def get_open_orders() -> Dict[str, Any]:
    """
    Retrieves all currently open limit and trigger orders for the configured wallet address.
    """
    try:
        orders = hl_info.open_orders(user_address)
        
        if not orders:
            return {"status": "success", "message": "No open orders found.", "orders": []}
            
        # Simplify the response structure for the tool user
        clean_orders = []
        for order in orders:
            clean_orders.append({
                "coin": order.get('coin'),
                "order_id": order.get('oid'),
                "side": "BUY" if order.get('side') == 'B' else "SELL",
                "limit_price": float(order.get('limitPx')),
                "size": float(order.get('sz')),
                "timestamp_ms": order.get('timestamp')
            })
            
        return {
            "status": "success",
            "message": f"Found {len(clean_orders)} open orders.",
            "orders": clean_orders
        }

    except Exception as e:
        print(f"CRITICAL ERROR during get_open_orders: {e}", file=sys.stderr)
        return {"error": f"Failed to retrieve open orders: {str(e)}"}

@mcp.tool()
async def get_all_perpetual_markets() -> Dict[str, Any]:
    """
    Retrieves a list of all perpetual contracts available for trading on HyperLiquid.
    """
    try:
        metadata = hl_info.meta()
        
        perpetuals = [
            asset['name'] 
            for asset in metadata.get('universe', []) 
            if asset.get('type') == 'perp'
        ]
        
        return {
            "status": "success",
            "message": f"Retrieved {len(perpetuals)} perpetual contracts.",
            "perpetual_contracts": perpetuals
        }
    
    except Exception as e:
        print(f"CRITICAL ERROR during get_all_perpetual_markets: {e}", file=sys.stderr)
        return {"error": f"Failed to retrieve market list: {str(e)}"}


# -------------------- TRADING TOOLS (EXCHANGE CLIENT) --------------------

@mcp.tool()
# FIX APPLIED: RENAMED to execute_market_order to bust the tool cache
async def execute_market_order(
    coin: str = Field(..., description="The asset symbol to trade (e.g., 'BTC', 'ETH')."),
    is_buy: bool = Field(..., description="True for a BUY order (go long/reduce short), False for a SELL order (go short/reduce long)."),
    size: float = Field(..., gt=0, description="The size of the order, must be greater than zero."),
    reduce_only: bool = Field(False, description="Set to True to ensure the order only reduces an existing position.")
) -> Dict[str, Any]:
    """
    Executes an immediate market order to buy or sell a specified size of an asset.
    This tool requires a valid private key for transaction signing.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}

    try:
        # Get the market price for the order type
        mid_price = await get_mid_price(coin)
        if mid_price <= 0:
            return {"error": "Could not retrieve valid market price to use for the order."}
            
        # For market orders, limit_px is set far from the mid price to guarantee a fill
        limit_px = mid_price * (1.05 if is_buy else 0.95)
            
        result = hl_exchange.order(
            coin=coin.upper(),
            is_buy=is_buy,
            sz=size,
            limit_px=limit_px, 
            order_type={"market": True}, 
            reduce_only=reduce_only
        )
        
        status_data = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
        
        if 'error' in status_data:
            return {"status": "failed", "exchange_error": status_data['error']}

        return {
            "status": "success",
            "message": f"Market order placed on {coin}.",
            "side": "BUY" if is_buy else "SELL",
            "size": size,
            "tx_hash": result.get('response', {}).get('hash')
        }

    except Exception as e:
        print(f"CRITICAL ERROR during market order placement: {e}", file=sys.stderr)
        return {"error": f"Failed to place order: {str(e)}"}

@mcp.tool()
# FIX APPLIED: Using scalar arguments to resolve the "not callable" error
async def place_limit_order(
    coin: str = Field(..., description="The asset symbol to trade (e.g., 'BTC', 'ETH')."),
    is_buy: bool = Field(..., description="True for a BUY order, False for a SELL order."),
    size: float = Field(..., gt=0, description="The size of the order, must be greater than zero."),
    limit_price: float = Field(..., gt=0, description="The specific price at which the order should be filled."),
    time_in_force: Literal["Gtc", "Ioc", "Alo"] = Field("Gtc", description="Time-in-Force. Gtc: Good-Til-Canceled (default). Ioc: Immediate-Or-Cancel. Alo: Add-Liquidity-Only (Post-Only)."),
    reduce_only: bool = Field(False, description="Set to True to ensure the order only reduces an existing position.")
) -> Dict[str, Any]:
    """
    Places a limit order to buy or sell a specified size at a specific price.
    This tool requires a valid private key for transaction signing.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}

    try:
        result = hl_exchange.order(
            coin=coin.upper(),
            is_buy=is_buy,
            sz=size,
            limit_px=limit_price,
            order_type={"limit": {"tif": time_in_force}}, 
            reduce_only=reduce_only
        )
        
        status_data = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
        
        if 'error' in status_data:
            return {"status": "failed", "exchange_error": status_data['error']}

        order_id = status_data.get('resting', {}).get('oid')
        
        return {
            "status": "success",
            "message": f"Limit order placed for {size} {coin} at {limit_price} with TIF: {time_in_force}.",
            "side": "BUY" if is_buy else "SELL",
            "order_id": order_id,
            "tx_hash": result.get('response', {}).get('hash')
        }

    except Exception as e:
        print(f"CRITICAL ERROR during limit order placement: {e}", file=sys.stderr)
        return {"error": f"Failed to place limit order: {str(e)}"}

@mcp.tool()
async def cancel_all_orders() -> Dict[str, Any]:
    """
    Cancels all open limit and trigger orders on the user's account across all assets.
    This tool is used for risk management and requires authorization.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}
    
    try:
        result = hl_exchange.cancel_all()

        tx_hash = result.get('response', {}).get('hash')
        
        if tx_hash:
            return {
                "status": "success",
                "message": "All open orders successfully submitted for cancellation.",
                "tx_hash": tx_hash
            }
        else:
            return {
                "status": "warning",
                "message": "Cancellation request submitted, but no immediate transaction hash was returned (may mean no open orders found)."
            }

    except Exception as e:
        print(f"CRITICAL ERROR during cancel_all: {e}", file=sys.stderr)
        return {"error": f"Failed to execute cancel_all: {str(e)}"}
    
@mcp.tool()
# FIX APPLIED: Using scalar arguments to resolve the "not callable" error
async def cancel_order_by_id(
    coin: str = Field(..., description="The asset symbol (e.g., 'BTC', 'ETH') of the order to cancel."),
    order_id: int = Field(..., gt=0, description="The unique numerical ID of the open order to cancel.")
) -> Dict[str, Any]:
    """
    Cancels a single, specific open order using its unique Order ID (oid).
    This tool requires a valid private key for transaction signing.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}
        
    try:
        result = hl_exchange.cancel(
            coin=coin.upper(),
            oid=order_id
        )

        tx_hash = result.get('response', {}).get('hash')
        status_data = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
        
        if 'error' in status_data:
            return {"status": "failed", "exchange_error": status_data['error']}
        
        return {
            "status": "success",
            "message": f"Cancellation request submitted for Order ID {order_id} on {coin}.",
            "order_id": order_id,
            "tx_hash": tx_hash
        }

    except Exception as e:
        print(f"CRITICAL ERROR during cancel_order_by_id: {e}", file=sys.stderr)
        return {"error": f"Failed to cancel order {order_id}: {str(e)}"}


# -------------------- 4. RUN THE SERVER --------------------
if __name__ == "__main__":
    print(f"Starting HyperLiquid MCP Server for address: {user_address} on {hl_env} environment. Waiting for client connection (STDIO)...", file=sys.stderr)
    mcp.run()