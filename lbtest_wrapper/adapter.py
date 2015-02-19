#!/usr/bin/python
from sys import stdin
from kafka import KafkaClient, SimpleProducer, SimpleConsumer
import json
import subprocess
import atexit
import os

class Adapter(object):
    curr_player = 0
    def _get_command(self, symbol):
        if(symbol == 'q'):
            command = {
                'event':'player_queued',
                'player': 'p' + str(self.curr_player)
            }
            self.curr_player += 1
            return command
        elif(symbol == 'd'):
            if (self.curr_player > 0):
                self.curr_player -= 1
            command = {
                'event':'player_dequeued',
                'player': 'p' + str(self.curr_player)
            }
            return command
        elif(symbol == 'r'):
            return {
                'event':'results_reported'
            }
        else:
            return {
                'event':'heartbeat'
            }


    def _send_testcase_messages(self, commands):
        command = self._get_command('')
        self.producer.send_messages('queue', json.dumps(command))
        if(len(commands) == 1 and commands[0] == ''):
            return
        for c in commands:
            command = self._get_command(c)
            self.producer.send_messages('queue', json.dumps(command))

    def _get_state_sequence(self):
        def get_state(in_game, number_in_queue):
            if (number_in_queue == 0):
                number_in_queue = 'zero'
            elif (number_in_queue == 1):
                number_in_queue = 'one'
            elif (number_in_queue >= 2):
                number_in_queue = 'two'
            if (in_game):
                in_game = 'yes'
            else:
                in_game = 'no'
            return in_game+';'+number_in_queue

        printstring = ""
        for message in self.consumer:
            payload = json.loads(message.message.value)
            if (not payload or 'event' in payload and payload['event'] != 'queue_info'):
                continue
            printstring += get_state(payload['in_game'], len(payload['players_in_queue']))+","
        return printstring


    def _rollback(self):
        def get_rollback_commands():
            deque = []
            while(self.curr_player > 0):
                self.curr_player -= 1
                deque.append({
                    'event':'player_dequeued',
                    'player': 'p' + str(self.curr_player)
                })
            return deque

        self.producer.send_messages('queue', json.dumps({
            'event':'results_reported'
        }))
        rollbacks = get_rollback_commands()
        for command in rollbacks:
            self.producer.send_messages('queue', json.dumps(command))



    def _save_state(self):
        def wait_for_cassandra():
            p = ""
            while("64 bytes from 192.168.56.101" not in p):
                try:
                    p = subprocess.check_output(["ping", "-c", "1", "-t", "1", "192.168.56.101"])
                except subprocess.CalledProcessError:
                    continue
        wait_for_cassandra()

        subprocess.call(["VBoxManage", "snapshot", "Cassandra 2.0.6", "take", "lbtest"], stdout = self.devnull, stderr = self.devnull)

    def execute_testcase(self, line):
        commands = line.split(",")
        self.consumer.seek(0, 2)
        self._send_testcase_messages(commands)
        printstring = self._get_state_sequence()
        self._rollback()
        return printstring[:-1]

    def __init__(self):
        self.devnull = open(os.devnull, 'w')
        self._save_state()
        kafka = KafkaClient('localhost:9092')
        self.consumer = SimpleConsumer(kafka, 'lbtest', 'queue', iter_timeout=0.1)
        self.producer = SimpleProducer(kafka)

        def exit_handler():
            subprocess.call(["VBoxManage", "controlvm", "Cassandra 2.0.6", "poweroff"], stdout = self.devnull, stderr = self.devnull)
            subprocess.call(["VBoxManage", "snapshot", "Cassandra 2.0.6", "restorecurrent"], stdout = self.devnull, stderr = self.devnull)
            subprocess.call(["VBoxManage", "startvm", "Cassandra 2.0.6"], stdout = self.devnull, stderr = self.devnull)

        atexit.register(exit_handler)

    def run(self):
        while(True):
            line = stdin.readline().strip()
            result = self.execute_testcase(line)
            print result

Adapter().run()
