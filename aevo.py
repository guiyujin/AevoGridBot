# # Description: Imports needed

# from clientConfig import clientConfig
from AlethieumAevoSDK import AevoClient
import asyncio
import json
from pprint import pprint
import pendulum
import time
import numpy as np
from loguru import logger

### CLIENT ###
# # Description: Please add your API key and secret to the clientConfig file.
# # Description: After importing the clientConfig, we can now create the client object.
# # Description: Please ensure that the clientConfig is correct before running the script.

CLIENT_CONFIG = {
    'signing_key': '',
    'wallet_address': '',
    'api_key': '',
    'api_secret': '',
    'env': 'mainnet',
}

client = AevoClient(**CLIENT_CONFIG)


### TASKS ###
# # Description: This section is for tasks

def get_midmarket_price(client, market):
    orderbook = client.get_orderbook(market)
    best_bid = float(orderbook["bids"][0][0])
    best_ask = float(orderbook["asks"][0][0])
    midmarket_price = np.mean([best_bid, best_ask])
    return round(midmarket_price, 2)
    # # Function: This task gets the midmarket price of the instrument.


### GRIDBOT CONFIG ###
# # Description: This file contains the tasks that will be executed by the celery worker

instrument_id = 1
instrument_name = "ETH-PERP"
orderSize = 0.01  # 订单金额大小，单位eth
gridSize = 1.5  # （网格大小,1就是1刀
gridLines = 20  # （网格数量）

### DATA ###
# # Description: This section is for data needed for the script

midmarket_price = get_midmarket_price(client, instrument_name)


### GRIDBOT ###
# # Description: This file contains the tasks that will be executed by the celery worker

async def aevo_gridbot():
    try:
        await client.open_connection()
        await client.subscribe_fills()

        async for msg in client.read_messages():
            message = json.loads(msg)
            if "data" in message and "success" in message["data"]:
                if message["data"]["success"]:
                    logger.info(f"🔌 Websocket connected at {pendulum.now()} to account {message['data']['account']}")
                    logger.info("🧑‍🍳 Starting Gridbot...")
                    for i in range(gridLines):
                        if i == 0:
                            bid_price = midmarket_price - (0.5 * gridSize)  # 在中心价格下方略微挂买单
                            ask_price = midmarket_price + (0.5 * gridSize)  # 在中心价格上方略微挂卖单
                        else:
                            bid_price = midmarket_price - (i * gridSize)
                            ask_price = midmarket_price + (i * gridSize)
                        await client.create_order(instrument_id, True, bid_price, orderSize)
                        await asyncio.sleep(0.2)  # 可以根据需要调整延迟时间
                        await client.create_order(instrument_id, False, ask_price, orderSize)
                        await asyncio.sleep(0.2)  # 可以根据需要调整延迟时间
            elif "data" in message and "fill" in message["data"]:  # 订单成交信息
                logger.info(f"fill: {message}")
                fill_price = float(message["data"]["fill"]["price"])
                filled = float(message["data"]["fill"]["filled"])  # 成交金额,如果要考虑网格线不会增加太多条的话,那就要判断全部成交的时候再创建新订单
                if message["data"]["fill"]["side"] == "buy":
                    await client.create_order(instrument_id, False, fill_price + gridSize, filled)
                elif message["data"]["fill"]["side"] == "sell":
                    await client.create_order(instrument_id, True, fill_price - gridSize, filled)
                await asyncio.sleep(0.2)
            elif "data" in message and "order_status" in message["data"]:
                if message["data"]["order_status"] == "cancelled" and message["error"] == "GTC_ORDER_REJECTED":
                    # 提取订单信息
                    side = message["data"]["side"]
                    price = float(message["data"]["price"])
                    amount = float(message["data"]["amount"])
                    # 重新提交订单
                    logger.info(f"Re-submitting order: side={side}, price={price}, amount={amount}")
                    is_buy = side == "buy"
                    await client.create_order(instrument_id, is_buy, price, amount)
                else:
                    logger.info(f"data: {message}")
            elif "data" in message and "error" in message and "ORDER_INVALID_SIGNING_KEY" in message["error"]:
                # 提取订单信息
                side = message["data"]["side"]
                price = float(message["data"]["price"])
                amount = float(message["data"]["amount"])
                # 重新提交订单
                logger.info(f"Re-submitting order: side={side}, price={price}, amount={amount}")
                is_buy = side == "buy"
                await client.create_order(instrument_id, is_buy, price, amount)
            else:
                logger.info(f"message: {message}")
    except Exception as e:
        logger.error(f"Connection closed unexpectedly: {e}")
        await client.cancel_all_orders()  # 确保正确调用取消订单的函数
        logger.info(f"Websocket disconnected at {pendulum.now()}, attempting to reconnect...")
        await asyncio.sleep(1)  # 等待一段时间后重试连接
        await aevo_gridbot()  # 递归地重新启动网格机器人


def start_gridbot():
    asyncio.get_event_loop().run_until_complete(aevo_gridbot())


start_gridbot()
