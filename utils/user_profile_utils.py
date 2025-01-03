from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from collections import Counter, defaultdict
from sqlalchemy.orm import sessionmaker
from utils.models import Contracts, User, Purchase  # Ensure these are correctly imported
from dexscreener import DexscreenerClient
import time
from functools import wraps, lru_cache
from typing import Union, List
import random
import requests
from flask import Flask, current_app
from utils.models import db


client = DexscreenerClient()
session = db.session
# print('PRINTTESTING~~~~~~~~~~~~~~~~~~~', type(session))

api_call_counter = Counter()

# def some_function():
#     with db.engine.connect() as connection:
#         result = connection.execute(db.session.query(Contracts).statement).fetchall()
#         print(result)
#         return result

def safe_get(obj, attr, default=None):
    """Helper function to safely access an attribute or return a default value."""
    try:
        return getattr(obj, attr, default) if obj is not None else default
    except AttributeError:
        return default

def rate_limited(max_per_second):
    """
    Decorator for basic rate limiting of function calls.
    """
    min_interval = 1.0 / float(max_per_second)
    
    def decorator(func):
        last_time_called = [0.0]
        
        @wraps(func)
        def rate_limited_function(*args, **kargs):
            elapsed = time.time() - last_time_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            ret = func(*args, **kargs)
            last_time_called[0] = time.time()
            return ret
        return rate_limited_function
    return decorator

def retry_with_backoff(func, max_retries=3, initial_delay=1, backoff_factor=2):
    """
    Decorator to retry API calls with exponential backoff in case of rate limiting.
    """
    def wrapper(*args, **kargs):
        retries = 0
        while retries < max_retries:
            try:
                return func(*args, **kargs)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    delay = initial_delay * (backoff_factor ** retries) + random.uniform(0, 1)
                    time.sleep(delay)
                    retries += 1
                else:
                    raise
        return None  # or handle as appropriate if all retries fail
    return wrapper

# @lru_cache(maxsize=128)
@retry_with_backoff
@rate_limited(1/2)  # 1 request per 2 seconds, if safe with API limits
def search_pairs_rate_limited(session, contract: Union[str, List[str]]):
    """
    Search for pairs with rate limiting and caching, and insert into SQL if new.
    
    :param session: SQLAlchemy session object for database operations
    :param contract: Either a single contract address as a string or a list of contract addresses
    :return: List of search results from the API call or None if there's an error
    """  
    # Ensure we're in the Flask application context
    with current_app.app_context():
        if isinstance(contract, list):
            search_query = ", ".join(contract)
        else:
            search_query = contract

        api_call_counter['search_pairs'] += 1
        
        try:
            search_results = client.search_pairs(search_query)
            
            if search_results:
                first_two_pairs_count = min(2, len(search_results))
                print(f'Found {first_two_pairs_count} of the first two pairs.')
                
                for pair in search_results:
                    contract_address = pair.pair_address      
                    # Use db.session directly to avoid confusion
                    existing_contract = db.session.query(Contracts).filter_by(contract_address=contract_address).first()
                    if not existing_contract:
                        new_contract = Contracts(
                            contract_address=contract_address,
                            base_token_address=pair.base_token.address,
                            quote_token_address=pair.quote_token.address,
                            chain_id=pair.chain_id,
                            dex_id=pair.dex_id
                        )
                        db.session.add(new_contract)
                db.session.commit()  
            
            # print(f"Search results for {search_query}:", search_results)
            return search_results
        except Exception as e:
            print(f"Error in search_pairs_rate_limited with query {search_query}: {e}")
            return None

def process_token_pairs(search):
    token_pairs = []
    for TokenPair in search:
        liquidity = TokenPair.liquidity if TokenPair.liquidity is not None else {}
        
        token_pairs.append({
            'pair': safe_get(TokenPair.base_token, 'name', 'N/A') + '/' + safe_get(TokenPair.quote_token, 'name', 'N/A'),
            'pool_address': safe_get(TokenPair, 'pair_address', 'N/A'),
            'pool_url': safe_get(TokenPair, 'url', 'N/A'),
            'price_usd': safe_get(TokenPair, 'price_usd', 0.0),
            'price_native': safe_get(TokenPair, 'price_native', 0.0),
            'liquidity_usd': safe_get(liquidity, 'usd', 0.0),
            'liquidity_base': safe_get(liquidity, 'base', 0.0),
            'liquidity_quote': safe_get(liquidity, 'quote', 0.0),
            'baseToken_address': safe_get(TokenPair.base_token, 'address', 'N/A'),
            'quoteToken_address': safe_get(TokenPair.quote_token, 'address', 'N/A'),
            'chain_id': safe_get(TokenPair, 'chain_id', 'N/A'),
            'dex_id': safe_get(TokenPair, 'dex_id', 'N/A'),
            'baseToken_name': safe_get(TokenPair.base_token, 'name', 'N/A'),
            'quoteToken_Name': safe_get(TokenPair.quote_token, 'name', 'N/A')
        })
    return token_pairs

def calculate_arbitrage_profit(initial_investment, price_pair1, price_pair2, slippage_pair1, slippage_pair2, fee_percentage, liquidity_pair1, liquidity_pair2):
    # Convert initial investment to amount in pair1
    amount_pair1 = initial_investment / price_pair1
    
    # Simplified slippage model
    def apply_slippage(amount, liquidity, slippage):
        return amount * (1 - slippage * (amount / float(liquidity)))  # Convert liquidity to float to ensure arithmetic operation works
    
    adjusted_amount_pair1 = apply_slippage(amount_pair1, liquidity_pair1, slippage_pair1)
    value_pair2 = adjusted_amount_pair1 * price_pair2
    final_amount_pair2 = apply_slippage(value_pair2, liquidity_pair2, slippage_pair2)
    
    # Calculate fees
    fees = initial_investment * fee_percentage * 2  # Considering two trades for fees
    
    # Profit calculation
    profit = final_amount_pair2 - initial_investment - fees
    
    return profit

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def find_arbitrage_opportunities(token_pairs, slippage_pair1, slippage_pair2, fee_percentage, initial_investment, user_purchases):
    logging.info('Starting arbitrage opportunity detection')
    arbitrage_opportunities = []
    total_pairs_checked = 0
    
    for i, pair1 in enumerate(token_pairs):
        for j, pair2 in enumerate(token_pairs):
            if i != j:  # Ensure pairs are different
                total_pairs_checked += 1
                # Check if pairs share a common token
                if (pair1['baseToken_address'] == pair2['baseToken_address'] or 
                    pair1['baseToken_address'] == pair2['quoteToken_address'] or 
                    pair1['quoteToken_address'] == pair2['baseToken_address']):
                    
                    logging.debug(f'Checking pair combination: {pair1["pair"]} and {pair2["pair"]}')
                    
                    # Determine price for comparison based on token matching
                    if pair1['baseToken_address'] == pair2['baseToken_address']:
                        pair1_price = float(pair1['price_native'])
                        pair2_price = float(pair2['price_native'])
                    elif pair1['baseToken_address'] == pair2['quoteToken_address']:
                        pair1_price = float(pair1['price_native'])
                        pair2_price = 1 / float(pair2['price_native'])  # Invert price since we're comparing base to quote
                    elif pair1['quoteToken_address'] == pair2['baseToken_address']:
                        pair1_price = 1 / float(pair1['price_native'])  # Invert price since we're comparing quote to base
                        pair2_price = float(pair2['price_native'])
                    else:
                        logging.debug(f'Skipping pair combination as no common token found for {pair1["pair"]} and {pair2["pair"]}')
                        continue  # This shouldn't happen due to our condition above, but added for robustness

                    # Check for sufficient liquidity
                    if float(pair1['liquidity_usd']) > 10000 and float(pair2['liquidity_usd']) > 10000:
                        
                        price_diff = pair2_price - pair1_price
                        liquidity_diff = float(pair1['liquidity_usd']) - float(pair2['liquidity_usd'])

                        # Determine which liquidity to use based on the direction of the arbitrage
                        if price_diff > 0:
                            # We use the liquidity of the token common in both pairs for base liquidity
                            if pair1['baseToken_address'] == pair2['baseToken_address']:
                                base_liquidity = min(float(pair1['liquidity_base']), float(pair2['liquidity_base']))
                            elif pair1['baseToken_address'] == pair2['quoteToken_address']:
                                base_liquidity = min(float(pair1['liquidity_base']), float(pair2['liquidity_quote']))
                            else:  # pair1['quoteToken_address'] == pair2['baseToken_address']
                                base_liquidity = min(float(pair1['liquidity_quote']), float(pair2['liquidity_base']))
                            
                            profit = calculate_arbitrage_profit(initial_investment, 
                                                                pair1_price, 
                                                                pair2_price, 
                                                                slippage_pair1, 
                                                                slippage_pair2, 
                                                                fee_percentage,
                                                                float(pair1['liquidity_base']) if pair1['baseToken_address'] in [pair2['baseToken_address'], pair2['quoteToken_address']] else float(pair1['liquidity_quote']),
                                                                float(pair2['liquidity_base']) if pair2['baseToken_address'] in [pair1['baseToken_address'], pair1['quoteToken_address']] else float(pair2['liquidity_quote']))
                            
                            if profit > 0:  # Only consider positive profit opportunities
                                logging.info(f'Found potential arbitrage opportunity: Profit = ${profit:.2f} for pairs {pair1["pair"]} and {pair2["pair"]}')
                                int_profit = int(profit * 10**8) / 10**8
                                
                                opportunity = {
                                    'pair1': pair1['pair'],
                                    'pair1_price': pair1['price_usd'],
                                    'pair1_price_round': f"{round(pair1['price_usd'], 8)}",
                                    'pair1_liquidity': f"${pair1['liquidity_usd']:,.2f}",
                                    'pair1_liquidity_base': f"{pair1['liquidity_base']:,.2f}",
                                    'pair1_liquidity_quote': f"{pair1['liquidity_quote']:,.2f}",
                                    'pool_pair1_address': pair1['pool_address'],
                                    'pair1_baseToken_address': pair1['baseToken_address'],
                                    'pair1_quoteToken_address': pair1['quoteToken_address'],
                                    'pool_pair1_url': pair1['pool_url'],
                                    'pair2': pair2['pair'],
                                    'pair2_price': pair2['price_usd'],
                                    'pair2_price_round': f"{round(pair2['price_usd'], 8)}",
                                    'pair2_liquidity': f"${pair2['liquidity_usd']:,.2f}",
                                    'pair2_liquidity_base': f"{pair2['liquidity_base']:,.2f}",
                                    'pair2_liquidity_quote': f"{pair2['liquidity_quote']:,.2f}",
                                    'pool_pair2_address': pair2['pool_address'],  
                                    'pair2_baseToken_address': pair2['baseToken_address'],
                                    'pair2_quoteToken_address': pair2['quoteToken_address'],
                                    'pool_pair2_url': pair2['pool_url'],
                                    'price_diff': f"${price_diff:,.2f}",
                                    'liquidity_diff': f"${liquidity_diff:,.2f}",
                                    'profit': f"${profit:,.2f}",
                                    'int_profit': int_profit,
                                    'potential_profit': f"${base_liquidity * price_diff:,.2f}",
                                    'pair1_chain_id': pair1['chain_id'],
                                    'pair1_dex_id': pair1['dex_id'], 
                                    'pair2_chain_id': pair2['chain_id'],
                                    'pair2_dex_id': pair2['dex_id'],
                                    'pair1_priceNative': pair1['price_native'],
                                    'pair2_priceNative': pair2['price_native'],
                                    'pair1_priceNative_round': f"{round(pair1['price_native'], 8)}",
                                    'pair2_priceNative_round': f"{round(pair2['price_native'], 8)}",
                                    'nativePrice_difference': price_diff,
                                }
                                
                                arbitrage_opportunities.append(opportunity)
                            else:
                                logging.debug(f'No profit for pairs {pair1["pair"]} and {pair2["pair"]}: Profit = ${profit:.2f}')
                        else:
                            logging.debug(f'Price difference not positive for {pair1["pair"]} and {pair2["pair"]}: {price_diff}')
                    else:
                        logging.debug(f'Insufficient liquidity for pair1: {pair1["pair"]} or pair2: {pair2["pair"]}')

    logging.info(f'Checked {total_pairs_checked} pair combinations. Found {len(arbitrage_opportunities)} arbitrage opportunities.')
    return arbitrage_opportunities

# Configure logging if not already done in the module where this function resides
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


from collections import Counter
def find_third_contract_data(unique_pair_addresses, arbitrage_opportunities, session, initial_investment, slippage_pair1, slippage_pair2, fee_percentage):        
    unique_pair_addresses = list(set(unique_pair_addresses))
    # 1. Log the start of the function
    logging.info('Starting to find third contract data')
    print("arbitrage_opportunities", type(arbitrage_opportunities))
    print("arbitrage_opportunities", type(arbitrage_opportunities))
    
    # 2. Initialize data structures
    seen_addresses = set()  # Store seen addresses to avoid duplicates
    third_pair_index = {}   # Dictionary to store potential third pairs

    # 3. Process each unique pair address for third pair data
    for contract in unique_pair_addresses:
        if contract not in seen_addresses:
            # 3.1. Add to seen addresses to avoid processing duplicates
            seen_addresses.add(contract)
            logging.info(f'Processing contract: {contract}')
            
            # 3.2. Search for pairs related to this contract
            search = search_pairs_rate_limited(session, contract)
            if search:
                for pair in search:
                    # 3.3. Filter pairs based on liquidity
                    liquidity_data = safe_get(pair, 'liquidity', {})
                    if hasattr(liquidity_data, 'usd') and liquidity_data.usd > 1:
                        logging.debug(f'Processing pair with sufficient liquidity: {pair.pair_address}')
                        
                        # 3.4. Extract details of the pair if it meets liquidity criteria
                        pair_details = {
                            'baseToken_address': safe_get(pair.base_token, 'address', 'N/A'),
                            'quoteToken_address': safe_get(pair.quote_token, 'address', 'N/A'),
                            'pair_address': safe_get(pair, 'pair_address', 'N/A'),
                            'pair': f"{safe_get(pair.base_token, 'name', 'N/A')}/{safe_get(pair.quote_token, 'name', 'N/A')}",
                            'price_usd': safe_get(pair, 'priceUsd', '0.0'),
                            'price_native': safe_get(pair, 'priceNative', '0.0'),
                            'liquidity': liquidity_data,
                            'url': safe_get(pair, 'url', 'N/A'),
                            'chain_id': safe_get(pair, 'chain_id', 'N/A'),
                            'dex_id': safe_get(pair, 'dex_id', 'N/A')
                        }
                        # 3.5. Add the pair to the index using its address as the key
                        third_pair_index[safe_get(pair, 'pair_address', 'N/A')] = pair_details
            else:
                # 3.6. Log if no search results were found for this contract
                logging.debug(f'No search results for contract {contract}')
        else:
            # 3.7. Skip already processed contracts
            logging.info(f'Skipping already seen address: {contract}')

    # 4. Log the number of third contracts indexed
    logging.info(f'Indexed {len(third_pair_index)} third contracts')
    
    # 5. Prepare to combine opportunities with third pair data
    combined_opportunities = []
    # arbitrage_opportunities = [opportunity._asdict() for opportunity in session.query(...).all()]
    # 6. Process each arbitrage opportunity to find a matching third pair
def find_third_contract_data(unique_pair_addresses, arbitrage_opportunities, session, initial_investment, slippage_pair1, slippage_pair2, fee_percentage):
    # 1. Log the start of the function
    logging.info('Starting to find third contract data')
    print("arbitrage_opportunities", type(arbitrage_opportunities))
    print("arbitrage_opportunities", type(arbitrage_opportunities))
    
    # 2. Initialize data structures
    seen_addresses = set()  # Store seen addresses to avoid duplicates
    third_pair_index = {}   # Dictionary to store potential third pairs
    combined_opportunities = []  # List to store combined opportunities
    seen_combined_opportunities = set()  # Set to track unique combinations

    # 3. Process each unique pair address for third pair data
    for contract in unique_pair_addresses:
        if contract not in seen_addresses:
            # 3.1. Add to seen addresses to avoid processing duplicates
            seen_addresses.add(contract)
            logging.info(f'Processing contract: {contract}')
            
            # 3.2. Search for pairs related to this contract
            search = search_pairs_rate_limited(session, contract)
            if search:
                for pair in search:
                    # 3.3. Filter pairs based on liquidity
                    liquidity_data = safe_get(pair, 'liquidity', {})
                    if hasattr(liquidity_data, 'usd') and liquidity_data.usd > 1:
                        logging.debug(f'Processing pair with sufficient liquidity: {pair.pair_address}')
                        
                        # 3.4. Extract details of the pair if it meets liquidity criteria
                        pair_details = {
                            'baseToken_address': safe_get(pair.base_token, 'address', 'N/A'),
                            'quoteToken_address': safe_get(pair.quote_token, 'address', 'N/A'),
                            'pair_address': safe_get(pair, 'pair_address', 'N/A'),
                            'pair': f"{safe_get(pair.base_token, 'name', 'N/A')}/{safe_get(pair.quote_token, 'name', 'N/A')}",
                            'price_usd': safe_get(pair, 'priceUsd', '0.0'),
                            'price_native': safe_get(pair, 'priceNative', '0.0'),
                            'liquidity': liquidity_data,
                            'url': safe_get(pair, 'url', 'N/A'),
                            'chain_id': safe_get(pair, 'chain_id', 'N/A'),
                            'dex_id': safe_get(pair, 'dex_id', 'N/A')
                        }
                        # 3.5. Add the pair to the index using its address as the key
                        third_pair_index[safe_get(pair, 'pair_address', 'N/A')] = pair_details
            else:
                # 3.6. Log if no search results were found for this contract
                logging.debug(f'No search results for contract {contract}')
        else:
            # 3.7. Skip already processed contracts
            logging.info(f'Skipping already seen address: {contract}')

    # 4. Log the number of third contracts indexed
    logging.info(f'Indexed {len(third_pair_index)} third contracts')
    
    # 6. Process each arbitrage opportunity to find a matching third pair
    for opportunity in arbitrage_opportunities:
        logging.debug(f'Processing opportunity for pair1: {opportunity["pair1"]}, pair2: {opportunity["pair2"]}')
        matched_pair = None
        
        # 6.1. Gather token addresses from the opportunity's pairs
        addresses = [
            opportunity['pair1_baseToken_address'],
            opportunity['pair1_quoteToken_address'],
            opportunity['pair2_baseToken_address'],
            opportunity['pair2_quoteToken_address']
        ]
        
        # 6.2. Find unique tokens that appear only once across the two pairs
        counter = Counter(addresses)
        unique_tokens = [addr for addr, count in counter.items() if count == 1]
        shared_tokens = [addr for addr, count in counter.items() if count > 1]

        # 6.3. Modify the logic to handle different scenarios
        if len(unique_tokens) == 2:
            # Existing logic for exactly two unique tokens
            unique_token1, unique_token2 = sorted(unique_tokens)
            for pair_address, pair_data in third_pair_index.items():
                if (pair_data['baseToken_address'] == unique_token1 and pair_data['quoteToken_address'] == unique_token2) or \
                   (pair_data['baseToken_address'] == unique_token2 and pair_data['quoteToken_address'] == unique_token1):
                    matched_pair = pair_data
                    logging.info(f'Matched third pair: {pair_data["pair"]}')
                    break
        elif len(unique_tokens) == 1 and len(shared_tokens) == 1:
            # If there's one unique token and one shared token
            unique_token = unique_tokens[0]
            shared_token = shared_tokens[0]
            for pair_address, pair_data in third_pair_index.items():
                if (pair_data['baseToken_address'] == unique_token and pair_data['quoteToken_address'] == shared_token) or \
                   (pair_data['baseToken_address'] == shared_token and pair_data['quoteToken_address'] == unique_token):
                    matched_pair = pair_data
                    logging.info(f'Matched third pair: {pair_data["pair"]}')
                    break
        elif len(shared_tokens) == 2:
            # If both tokens from the first two pairs are shared
            shared_token1, shared_token2 = sorted(shared_tokens)
            for pair_address, pair_data in third_pair_index.items():
                if (pair_data['baseToken_address'] == shared_token1 and pair_data['quoteToken_address'] == shared_token2) or \
                   (pair_data['baseToken_address'] == shared_token2 and pair_data['quoteToken_address'] == shared_token1):
                    matched_pair = pair_data
                    logging.info(f'Matched third pair: {pair_data["pair"]}')
                    break
        else:
            # Log or handle cases where no clear match can be found
            logging.debug(f"Complex token configuration for opportunity: {opportunity}")
            matched_pair = None

        # 6.4. Update the opportunity with third pair data if a match is found
        if matched_pair:
            combined_opportunity = opportunity.copy()
            combined_opportunity.update({
                'pair3': matched_pair['pair'],
                'pair3_price': matched_pair['price_usd'],
                'pair3_price_round': f"{round(float(matched_pair['price_usd']), 8)}",
                'pair3_liquidity': f"${safe_get(matched_pair['liquidity'], 'usd', 0.0):,.2f}",
                'pair3_liquidity_base': f"{safe_get(matched_pair['liquidity'], 'base', 0.0):,.2f}",
                'pair3_liquidity_quote': f"{safe_get(matched_pair['liquidity'], 'quote', 0.0):,.2f}",
                'pool_pair3_address': matched_pair['pair_address'],
                'pair3_baseToken_address': matched_pair['baseToken_address'],
                'pair3_quoteToken_address': matched_pair['quoteToken_address'],
                'pool_pair3_url': matched_pair['url'],
                'pair3_chain_id': matched_pair['chain_id'],
                'pair3_dex_id': matched_pair['dex_id'],
                'pair3_priceNative': matched_pair['price_native'],
                'pair3_priceNative_round': f"{round(float(matched_pair['price_native']), 8)}"
            })
            
            # Ensure uniqueness by creating a tuple of sorted pair names
            opportunity_key = tuple(sorted([combined_opportunity['pair1'], combined_opportunity['pair2'], combined_opportunity['pair3']]))
            if opportunity_key not in seen_combined_opportunities:
                seen_combined_opportunities.add(opportunity_key)
                combined_opportunities.append(combined_opportunity)
                logging.debug(f'Added unique opportunity: {combined_opportunity}')
            else:
                logging.debug(f'Skipped duplicate opportunity: {combined_opportunity}')

    # 7. Log the final number of opportunities processed
    logging.info(f'Final number of arbitrage opportunities with third pair: {len(combined_opportunities)}')

    # 8. Return the list of combined opportunities
    return combined_opportunities

def get_user_purchases(user_id):
    """
    Fetch all purchases associated with a user ID from the database.
    """
    return Purchase.query.filter_by(user_id=user_id).all()

def gather_token_pairs_from_purchases(purchases, session):
    """
    Gather all token pairs from the user's purchase history with rate limiting.
    """
    baseToken_addresses = [purchase.baseToken_address for purchase in purchases]
    all_token_pairs = []
    for address in baseToken_addresses:
        search = search_pairs_rate_limited(db.session, address)
        if search:
            all_token_pairs.extend(process_token_pairs(search))
    return all_token_pairs

def find_arbitrage_opportunities_for_user(token_pairs, purchases, slippage_pair1, slippage_pair2, fee_percentage, initial_investment):
    """
    Find arbitrage opportunities based on user's token pairs.
    """
    return find_arbitrage_opportunities(token_pairs, slippage_pair1, slippage_pair2, fee_percentage, initial_investment, purchases)

def filter_and_process_opportunities(opportunities):
    """
    Filter opportunities to only include those where there are more than two unique addresses.
    """
    quote_pairs = []
    pair_chains = []

    for opportunity in opportunities:
        addresses = [
            opportunity['pair1_baseToken_address'],
            opportunity['pair1_quoteToken_address'],
            opportunity['pair2_baseToken_address'],
            opportunity['pair2_quoteToken_address']
        ]
        if opportunity['pair1_chain_id'] == opportunity['pair2_chain_id']:
            counter = Counter(addresses)
            repeated_item = next(item for item, count in counter.items() if count > 1)
            unique_items = tuple(item for item in addresses if item != repeated_item)
            quote_pairs.append(unique_items)
            pair_chains.append(opportunity['pair1_chain_id'])
    
    return quote_pairs, pair_chains

def match_pairs_with_opportunities(opportunities, quote_pairs, pair_chains):
    """
    Match the arbitrage opportunities with corresponding token pairs from the Dexscreener data.
    """
    seen_searches = defaultdict(bool)
    matching_pairs = []
    combined_data = list(zip(quote_pairs, pair_chains))

    for item in combined_data:
        address1, address2, chain_id = item[0][0], item[0][1], item[1]
        search_key = f"{chain_id}_{address1}"
        if not seen_searches[search_key]:
            seen_searches[search_key] = True
            search = client.get_token_pairs(address1)
            for pair in search:
                if pair.quote_token.address == address2 or pair.base_token.address == address2:
                    matching_pairs.append(pair)
                    break
            if item != combined_data[-1]:
                time.sleep(3)  # Delay to avoid rate limiting

    opportunities_with_pairs = []
    for opportunity in opportunities:
        new_opportunity = opportunity.copy()
        new_opportunity['matching_pairs'] = [pair for pair in matching_pairs if 
            pair.base_token.address in [opportunity['pair1_baseToken_address'], opportunity['pair1_quoteToken_address'], opportunity['pair2_baseToken_address'], opportunity['pair2_quoteToken_address']] or
            pair.quote_token.address in [opportunity['pair1_baseToken_address'], opportunity['pair1_quoteToken_address'], opportunity['pair2_baseToken_address'], opportunity['pair2_quoteToken_address']]
        ]
        opportunities_with_pairs.append(new_opportunity)

    return opportunities_with_pairs