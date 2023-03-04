import json
import logging
import os
import queue
import random
import string
import sys
from pathlib import Path
from threading import Thread

from jhcompute import ssh
from jhcompute.searching import active_nodes_user_count


class Pool:

    def __init__(self, node_count: int, job_file: str) -> None:

        self.python_path = sys.executable
        self.node_count = node_count
        self.temp_dir = os.path.dirname(os.path.realpath(__file__)) + "/"

        # make temp directory

        try:
            os.mkdir(self.temp_dir)

        except FileExistsError as e:
            if Path(self.temp_dir).is_file():
                raise e

        # validate job file

        self.job_file = Path(job_file).resolve()

        if not self.job_file.is_file():
            raise FileNotFoundError(f"Can't find job file \"{job_file}\"...")

        logging.info(f"Loaded {self.job_file} as job file")

        # find nodes

        potential_nodes = active_nodes_user_count()

        logging.info(f"Found active potential {len(potential_nodes)}")

        if len(potential_nodes) < self.node_count:
            raise RuntimeError(f"Too few nodes active -- found only {len(potential_nodes)}")

        chosen_nodes = potential_nodes[:self.node_count]

        for node in filter(lambda n: n[1] > 0, chosen_nodes):
            logging.warning(f"{node[0]} already has {node[1]} user(s)...")

        self.nodes = [Node(self, node[0]) for node in chosen_nodes]
        self.free_nodes = queue.Queue()
        [self.free_nodes.put(node) for node in self.nodes]

        logging.info(f"Using initial nodes: {chosen_nodes}")

        # initialise queue

        self.job_queue = queue.Queue()

    def write_to_temp(self, json_object: dict):

        filename = self.temp_dir + f"{''.join(random.choices(string.ascii_letters, k=32))}.json"

        while Path(filename).is_file():
            filename = self.temp_dir + f"{''.join(random.choices(string.ascii_letters, k=32))}.json"

        with open(filename, "w") as file:
            json.dump(json_object, file)

        return filename

    def submit(self, task_object: dict) -> dict:
        node = self.free_nodes.get()
        result = node.run_task(task_object)  # TODO ignore node death for the min :)
        self.free_nodes.put(node)
        return result


class Node:

    def __init__(self, pool: Pool, hostname: str):
        self.hostname = hostname
        self.pool = pool

    def run_task(self, task_object: dict) -> dict:

        object_file = self.pool.write_to_temp(task_object)  # TODO clean up this file

        try:
            result = ssh.run_command(self.hostname, [
                self.pool.python_path,
                self.pool.job_file,
                object_file
            ])

        except (ConnectionAbortedError, ConnectionError):
            raise RuntimeError(f"Node {self.hostname} died!")  # TODO replace this node

        if result.returncode == 0:

            with open(object_file, "r") as file:
                return_object = json.load(file)

            os.remove(object_file)
            return return_object

        else:
            raise RuntimeError("Node execution failed: " + result.stdout + result.stderr)
