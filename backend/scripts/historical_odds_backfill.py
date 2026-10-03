class HistoricalOddsBackfill:
    def __init__(self):
        self.pit_safe = True
        
    def backfill(self, records: list):
        valid_records = []
        for r in records:
            # Ensure timestamp exists and is before kickoff (zero lookahead)
            if 'quote_timestamp' in r and 'kickoff_timestamp' in r:
                if r['quote_timestamp'] < r['kickoff_timestamp']:
                    valid_records.append(r)
                else:
                    self.pit_safe = False
                    # quarantine record
            else:
                self.pit_safe = False
        return valid_records
