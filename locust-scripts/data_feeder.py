
import os
import time
import zmq
import queue
import csv
import logging


FEEDER_HOST = os.getenv('FEEDER_HOST', '127.0.0.1')
FEEDER_BIND_PORT = os.getenv('FEEDER_BIND_PORT', 5555)
HH_FILE = os.getenv('HH_FILE', 'households.csv')


# use generated households on runtime, or load from CSV
def load_households():
    path = os.path.join(os.path.dirname(__file__), os.pardir, 'data', HH_FILE)
    with open(path, newline='') as csvfile:

        household_csv = csv.DictReader(csvfile)
        households = [row for row in household_csv]
        return households


class ZMQFeeder:
    def __init__(self, data, address='tcp://127.0.0.1:5555'):
        self.data = data

        context = zmq.Context()
        self.socket = context.socket(zmq.REP)
        self.socket.bind(address)
        print("zmq feeder initialized")

    def reset_data(self):
        print('Reset data')
        self.data_queue = queue.Queue()
        [self.data_queue.put(i) for i in self.data]

    def run(self):
        print("start sending...")
        while True:
            print("waiting for worker")
            response = self.socket.recv_json()
            print("received message")
            if response.get('start', False) is True:
                self.reset_data()
                self.socket.send_json({'done': True})
            if response.get('available', False) is True:
                try:
                    work = self.data_queue.get(block=False)
                    self.socket.send_json(work)
                    self.data_queue.task_done()
                except queue.Empty:
                    print("Queue empty. Reply empty to let worker know.")
                    self.socket.send_json({})
            # yield
            time.sleep(0)


INPUT_DATA = load_households()
sender = ZMQFeeder(INPUT_DATA, f"tcp://0.0.0.0:{FEEDER_BIND_PORT}")
sender.run()
