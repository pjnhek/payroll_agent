"""Email gateway package — the ONE provider seam (EMAIL-01).

parse_inbound / send_outbound are the entire provider abstraction; the real
provider swaps in at P6 touching only app/email/gateway.py.
"""
