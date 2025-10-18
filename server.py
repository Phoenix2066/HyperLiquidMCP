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
        key_bytes = private_key.lower().replace('0x', '')
        hl_account = Account.from_key(key_bytes)
        user_address = hl_account.address
        
    except ValueError as e:
        is_key_valid = False
        print(f"ERROR: Invalid Private Key format in .env: {e}", file=sys.stderr)
    except Exception as e:
        is_key_valid = False
        print(f"An unexpected error occurred during key setup: {e}", file=sys.stderr)


# Client Setup (Info client is always safe)
hl_info = Info() 

# Client Setup (Exchange client - only initialize if key is valid)
if is_key_valid:
    try:
        # Pass the hl_account object
        hl_exchange = Exchange(hl_account)
    except TypeError as e:
        hl_exchange = None
        print(f"CRITICAL ERROR: Failed to initialize Exchange client: {e}", file=sys.stderr)
        is_key_valid = False
else:
    hl_exchange = None


# --- 2. PYDANTIC MODELS FOR TOOL INPUTS ---

class MarketOrderInput(BaseModel):
    """Defines input parameters for placing a market order."""
    coin: str = Field(..., description="The asset symbol to trade (e.g., 'BTC', 'ETH').")
    is_buy: bool = Field(..., description="True for a BUY order (go long/reduce short), False for a SELL order (go short/reduce long).")
    size: float = Field(..., gt=0, description="The size of the order, must be greater than zero.")
    reduce_only: bool = Field(False, description="Set to True to ensure the order only reduces an existing position.")

class LimitOrderInput(BaseModel):
    """Defines input parameters for placing a limit order."""
    coin: str = Field(..., description="The asset symbol to trade (e.g., 'BTC', 'ETH').")
    is_buy: bool = Field(..., description="True for a BUY order, False for a SELL order.")
    size: float = Field(..., gt=0, description="The size of the order, must be greater than zero.")
    limit_price: float = Field(..., gt=0, description="The specific price at which the order should be filled.")
    time_in_force: Literal["Gtc", "Ioc", "Alo"] = Field("Gtc", description="Time-in-Force. Gtc: Good-Til-Canceled (default). Ioc: Immediate-Or-Cancel. Alo: Add-Liquidity-Only (Post-Only).")
    reduce_only: bool = Field(False, description="Set to True to ensure the order only reduces an existing position.")

class CancelOrderInput(BaseModel):
    """Defines input parameters for canceling a specific order."""
    coin: str = Field(..., description="The asset symbol (e.g., 'BTC', 'ETH') of the order to cancel.")
    order_id: int = Field(..., gt=0, description="The unique numerical ID of the open order to cancel.")
    
class CandlestickInput(BaseModel):
    """Defines input parameters for retrieving candlestick data."""
    coin: str = Field(..., description="The asset symbol (e.g., 'BTC', 'ETH').")
    interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"] = Field(
        ..., description="The desired time interval per candlestick (e.g., '1h', '1d')."
    )
    limit: int = Field(100, gt=0, le=1000, description="The maximum number of recent candles to retrieve (1 to 1000).")


# --- 3. FASTMCP SERVER DEFINITION ---

mcp = FastMCP(
    name="HyperLiquid DEX Tester",
    instructions="Provides read-only market data and authorized trading tools for HyperLiquid DEX."
)

#--- READ-ONLY TOOLS (INFO CLIENT) ---

#--- Get details from the users's provided wallet ---
@mcp.tool()
async def get_user_state() -> Dict[str, Any]:
    """
    Retrieves the user's current account state (balances, margin, and positions) 
    for the configured wallet address.
    """
    if not is_key_valid:
        # Still useful to query balance even without trading, but warn if key is missing
        print("WARNING: Private key is invalid or missing, proceeding with read-only state query.", file=sys.stderr)
        
    state = hl_info.user_state(user_address)
    return state

#--- Get the current mid price of the coin input.
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
        return {"error": f"Failed to retrieve price data for {coin}: {str(e)}"}

# --- Get User's Open Orders ---
@mcp.tool()
async def get_open_orders() -> Dict[str, Any]:
    """
    Retrieves all currently open limit and trigger orders for the configured wallet address.
    """
    # Note: Using user_address which is available even if key is invalid.
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

# --- Get List of All Available Perpetual Contracts ---
@mcp.tool()
async def get_all_perpetual_markets() -> Dict[str, Any]:
    """
    Retrieves a list of all perpetual contracts available for trading on HyperLiquid.
    This is useful for market discovery and input validation for other tools.
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

#--- TRADING TOOLS (EXCHANGE CLIENT - REQUIRE VALID KEY) ---

# --- Place a Market Order (Original) ---
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
            
        # For market orders, limit_px is set far from the mid price to guarantee a fill
        limit_px = mid_price * (1.05 if order.is_buy else 0.95)
            
        result = hl_exchange.order(
            coin=order.coin.upper(),
            is_buy=order.is_buy,
            sz=order.size,
            limit_px=limit_px, 
            order_type={"market": True}, 
            reduce_only=order.reduce_only
        )
        
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

# --- Place a Limit Order (New) ---
@mcp.tool()
async def place_limit_order(order: LimitOrderInput) -> Dict[str, Any]:
    """
    Places a limit order to buy or sell a specified size at a specific price.
    This tool requires a valid private key for transaction signing.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}

    try:
        # Place the order using the Exchange client
        result = hl_exchange.order(
            coin=order.coin.upper(),
            is_buy=order.is_buy,
            sz=order.size,
            limit_px=order.limit_price,
            order_type={"limit": {"tif": order.time_in_force}}, 
            reduce_only=order.reduce_only
        )
        
        status_data = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
        
        if 'error' in status_data:
             return {"status": "failed", "exchange_error": status_data['error']}

        order_id = status_data.get('resting', {}).get('oid')
        
        return {
            "status": "success",
            "message": f"Limit order placed for {order.size} {order.coin} at {order.limit_price} with TIF: {order.time_in_force}.",
            "side": "BUY" if order.is_buy else "SELL",
            "order_id": order_id,
            "tx_hash": result.get('response', {}).get('hash')
        }

    except Exception as e:
        print(f"CRITICAL ERROR during limit order placement: {e}", file=sys.stderr)
        return {"error": f"Failed to place limit order: {str(e)}"}

# --- Cancel All Open Orders (Original) ---
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
    
# --- Cancel a Specific Order by ID (New) ---
@mcp.tool()
async def cancel_order_by_id(cancel_input: CancelOrderInput) -> Dict[str, Any]:
    """
    Cancels a single, specific open order using its unique Order ID (oid).
    This tool requires a valid private key for transaction signing.
    """
    if not is_key_valid or not hl_exchange:
        return {"error": "Trading is disabled. Private key is invalid or Exchange client failed to initialize."}
        
    try:
        result = hl_exchange.cancel(
            coin=cancel_input.coin.upper(),
            oid=cancel_input.order_id
        )

        tx_hash = result.get('response', {}).get('hash')
        status_data = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
        
        if 'error' in status_data:
             return {"status": "failed", "exchange_error": status_data['error']}
        
        return {
            "status": "success",
            "message": f"Cancellation request submitted for Order ID {cancel_input.order_id} on {cancel_input.coin}.",
            "order_id": cancel_input.order_id,
            "tx_hash": tx_hash
        }

    except Exception as e:
        print(f"CRITICAL ERROR during cancel_order_by_id: {e}", file=sys.stderr)
        return {"error": f"Failed to cancel order {cancel_input.order_id}: {str(e)}"}


# --- 4. RUN THE SERVER ---
if __name__ == "__main__":
    print(f"Starting HyperLiquid MCP Server for address: {user_address}. Waiting for client connection (STDIO)...", file=sys.stderr)
    mcp.run()