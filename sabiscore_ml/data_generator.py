import pandas as pd
from datetime import timedelta
import gc

def generate_walk_forward_batches(db_engine, start_date, end_date, train_days=365, test_days=30, step_days=30):
    current_train_start = pd.to_datetime(start_date)
    final_date = pd.to_datetime(end_date)
    fold = 1

    while True:
        current_train_end = current_train_start + timedelta(days=train_days)
        current_test_end = current_train_end + timedelta(days=test_days)

        if current_test_end > final_date:
            break 

        train_query = f"""
            SELECT * FROM match_features 
            WHERE match_date >= '{current_train_start.strftime('%Y-%m-%d')}' 
            AND match_date < '{current_train_end.strftime('%Y-%m-%d')}'
        """
        
        test_query = f"""
            SELECT * FROM match_features 
            WHERE match_date >= '{current_train_end.strftime('%Y-%m-%d')}' 
            AND match_date < '{current_test_end.strftime('%Y-%m-%d')}'
        """

        df_train = pd.read_sql(train_query, db_engine)
        df_test = pd.read_sql(test_query, db_engine)

        yield fold, df_train, df_test, current_train_end
        
        del df_train, df_test
        gc.collect()

        current_train_start += timedelta(days=step_days)
        fold += 1
