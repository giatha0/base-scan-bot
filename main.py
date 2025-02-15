import os
import time
import requests
import logging
import json
import datetime
from web3 import Web3
from web3._utils.events import get_event_data  # Dùng để decode log sự kiện

logging.basicConfig(level=logging.INFO, format="%(message)s")

# Đọc biến môi trường
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS")
BASESCAN_API_KEY = os.environ.get("BASESCAN_API_KEY")  # Có thể bỏ qua nếu không cần
RPC_URL = os.environ.get("RPC_URL")  # Ví dụ: https://base-mainnet.g.alchemy.com/v2/...
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if (WALLET_ADDRESS is None or RPC_URL is None or 
    TELEGRAM_BOT_TOKEN is None or TELEGRAM_CHAT_ID is None):
    logging.error("Bạn cần thiết lập WALLET_ADDRESS, RPC_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID!")
    exit(1)

MAX_RPC_FAILS = 10
rpc_fail_count = 0

########################
# Hàm gửi thông báo Telegram
########################
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"  # Sử dụng Markdown để tạo liên kết và code block
    }
    try:
        resp = requests.post(url, data=payload, timeout=5)
        resp.raise_for_status()
        logging.info("Đã gửi thông báo Telegram thành công.")
    except Exception as e:
        logging.error(f"Lỗi khi gửi thông báo Telegram: {e}")

########################
# ABI cho hàm deployToken (để decode input data)
########################
deployToken_abi = [
    {
        "name": "deployToken",
        "type": "function",
        "inputs": [
            {
                "name": "preSaleTokenConfig",
                "type": "tuple",
                "components": [
                    {"name": "name", "type": "string"},
                    {"name": "symbol", "type": "string"},
                    {"name": "supply", "type": "uint256"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "salt", "type": "bytes32"},
                    {"name": "deployer", "type": "address"},
                    {"name": "fid", "type": "uint256"},
                    {"name": "image", "type": "string"},
                    {"name": "castHash", "type": "string"},
                    {
                        "name": "poolConfig",
                        "type": "tuple",
                        "components": [
                            {"name": "tick", "type": "int24"},
                            {"name": "pairedToken", "type": "address"},
                            {"name": "devBuyFee", "type": "uint24"}
                        ]
                    }
                ]
            }
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    }
]

w3 = Web3()  # Dùng để decode input data (không cần provider)
contract = w3.eth.contract(abi=deployToken_abi)

def decode_input_data_abi(input_hex):
    try:
        _, params = contract.decode_function_input(input_hex)
        return params["preSaleTokenConfig"]
    except Exception as e:
        logging.error(f"Decode input data error: {e}")
        return None

########################
# Lấy giao dịch mới nhất từ Basescan
########################
def get_latest_transaction():
    url = "https://api.basescan.org/api"
    params = {
        "module": "account",
        "action": "txlist",
        "address": WALLET_ADDRESS,
        "sort": "desc",
    }
    if BASESCAN_API_KEY:
        params["apikey"] = BASESCAN_API_KEY
    try:
        response = requests.get(url, params=params, timeout=9)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "1" and data.get("result"):
            logging.info("Lấy giao dịch thành công từ Basescan.")
            return data["result"][0]
        else:
            logging.info("Không có giao dịch nào được trả về hoặc trạng thái không hợp lệ.")
    except Exception as e:
        logging.error(f"Lỗi khi lấy giao dịch: {e}")
    return None

########################
# Lấy thông tin ERC-20 Transfer
########################
transfer_event_abi = {
    "anonymous": False,
    "inputs": [
        {"indexed": True, "name": "from", "type": "address"},
        {"indexed": True, "name": "to", "type": "address"},
        {"indexed": False, "name": "value", "type": "uint256"}
    ],
    "name": "Transfer",
    "type": "event"
}
TRANSFER_EVENT_SIG = Web3.keccak(text="Transfer(address,address,uint256)").hex()

def get_erc20_transfer(tx_hash, rpc_url):
    global rpc_fail_count
    w3_rpc = Web3(Web3.HTTPProvider(rpc_url))
    try:
        receipt = w3_rpc.eth.get_transaction_receipt(tx_hash)
    except Exception as e:
        rpc_fail_count += 1
        logging.error(f"Lỗi khi lấy receipt (lần {rpc_fail_count}): {e}")
        if rpc_fail_count >= MAX_RPC_FAILS:
            logging.error("RPC_URL lỗi quá nhiều lần. Dừng chương trình.")
            exit(1)
        return None
    for log in receipt.logs:
        if log.topics and log.topics[0].hex() == TRANSFER_EVENT_SIG:
            try:
                _ = get_event_data(w3_rpc.codec, transfer_event_abi, log)
                return log.address  # Trả về địa chỉ token contract
            except Exception as e:
                logging.error(f"Decode log Transfer error: {e}")
    return None

########################
# Lấy tên token ERC-20
########################
erc20_abi = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }
]

def get_token_name(token_address, rpc_url):
    global rpc_fail_count
    w3_rpc = Web3(Web3.HTTPProvider(rpc_url))
    try:
        token_contract = w3_rpc.eth.contract(address=token_address, abi=erc20_abi)
        return token_contract.functions.name().call()
    except Exception as e:
        rpc_fail_count += 1
        logging.error(f"Lỗi khi lấy tên token (lần {rpc_fail_count}): {e}")
        if rpc_fail_count >= MAX_RPC_FAILS:
            logging.error("RPC_URL lỗi quá nhiều lần. Dừng chương trình.")
            exit(1)
        return None

########################
# Main loop
########################
def main():
    # Gửi tin nhắn Telegram thông báo khởi chạy
    start_message = f"[Railway Start]\nỨng dụng đã khởi chạy tại: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    send_telegram_message(start_message)
    
    last_tx_hash = None
    while True:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"Polling tại: {current_time}")
        
        tx = get_latest_transaction()
        if tx:
            current_hash = tx.get("hash")
            if current_hash != last_tx_hash:
                input_data_hex = tx.get("input", "")
                cast_hash = None
                if input_data_hex and input_data_hex != "0x":
                    decoded = decode_input_data_abi(input_data_hex)
                    if decoded and "castHash" in decoded:
                        cast_hash = decoded["castHash"]
                
                # Chỉ xử lý nếu castHash == "bankr deployment"
                if cast_hash == "bankr deployment":
                    token_contract = get_erc20_transfer(current_hash, RPC_URL)
                    token_name = None
                    if token_contract:
                        token_name = get_token_name(token_contract, RPC_URL)
                    
                    # Tạo liên kết cho Tx hash: liên kết đến Basescan
                    tx_link = f"[Tx hash](https://basescan.org/tx/{current_hash})"
                    
                    # Tạo dòng liên kết cho token (TokenTx | Chart | X) nếu token_contract tồn tại
                    token_links = ""
                    if token_contract:
                        token_links = (
                            f"[TokenTx](https://basescan.org/token/{token_contract}) | "
                            f"[Chart](https://dexscreener.com/base/{token_contract}) | "
                            f"[X](https://x.com/search?q={token_contract})"
                        )
                    
                    # Dùng backticks để người dùng có thể copy contract
                    contract_text = f"`{token_contract}`" if token_contract else "`Không tìm thấy`"
                    
                    log_message = (
                        "==========================================\n"
                        f"{tx_link}\n"
                        f"castHash: {cast_hash}\n"
                        f"Erc20 Contract: {contract_text}\n"
                        f"Ticket: {token_name if token_name else 'Không lấy được tên'}\n"
                        f"{token_links}"
                    )
                    logging.info(log_message)
                    
                    # Gửi thông báo Telegram
                    send_telegram_message(f"[BANKR DEPLOYMENT]\n{log_message}")
                else:
                    logging.info("Không phải bankr deployment, bỏ qua giao dịch này.")
                
                last_tx_hash = current_hash
            else:
                logging.info("Không có giao dịch mới.")
        else:
            logging.info("Không lấy được giao dịch.")
        time.sleep(1)

if __name__ == "__main__":
    main()