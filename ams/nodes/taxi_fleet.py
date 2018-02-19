#!/usr/bin/env python
# coding: utf-8

from time import time

from ams import Topic, Route, Schedule
from ams.nodes import FleetManager, User, TaxiUser, Vehicle, SimTaxi
from ams.messages import UserStatus, VehicleStatus
from ams.structures import Target, TAXI_FLEET
from pprint import PrettyPrinter
pp = PrettyPrinter(indent=2).pprint


class TaxiFleet(FleetManager):

    CONST = TAXI_FLEET

    def __init__(self, name, waypoint, arrow, route):
        super().__init__(name, waypoint, arrow, route)

        self.topicUserPublish = Topic()
        self.topicUserPublish.set_root(User.CONST.TOPIC.PUBLISH)

        self.topicUserSubscribe = Topic()
        self.topicUserSubscribe.set_root(User.CONST.TOPIC.SUBSCRIBE)

        self.topicVehicleStatus = Topic()
        self.topicVehicleStatus.set_root(Vehicle.CONST.TOPIC.PUBLISH)

        self.topicVehicleSchedules = Topic()
        self.topicVehicleSchedules.set_root(Vehicle.CONST.TOPIC.SUBSCRIBE)

        self.waypoint = waypoint
        self.arrow = arrow
        self.route = route

        self.user_statuses = {}
        self.user_schedules = {}
        self.vehicle_statuses = {}
        self.vehicle_schedules = {}

        self.add_on_message_function(self.update_user_status)
        self.add_on_message_function(self.update_vehicle_status)

        self.set_subscriber(self.topicUserPublish.all)
        self.set_subscriber(self.topicVehicleStatus.all)

    def update_user_status(self, _client, _userdata, topic, payload):
        if self.topicUserPublish.root in topic:
            user_id = self.topicUserPublish.get_id(topic)
            user_status = UserStatus.new_data(**self.topicUserPublish.unserialize(payload))
            self.user_statuses[user_id] = user_status
            if user_id not in self.user_schedules:
                self.user_schedules[user_id] = [user_status.schedule]

    def update_vehicle_status(self, _client, _userdata, topic, payload):
        if self.topicVehicleStatus.root in topic:
            vehicle_id = self.topicVehicleStatus.get_id(topic)
            vehicle_status = VehicleStatus.new_data(**self.topicVehicleStatus.unserialize(payload))
            if vehicle_id not in self.vehicle_schedules:
                self.vehicle_schedules[vehicle_id] = [vehicle_status.schedule]
            else:
                if self.vehicle_statuses[vehicle_id].state != vehicle_status.state:
                    self.update_vehicle_schedules(vehicle_id, vehicle_status)
            self.vehicle_statuses[vehicle_id] = vehicle_status

    def update_vehicle_schedules(self, vehicle_id, vehicle_status):
        self.vehicle_schedules[vehicle_id].pop(0)
        self.vehicle_schedules[vehicle_id][0] = vehicle_status.schedule

    def get_dispatchable_vehicle_ids(self, user_id):
        dispatchable_vehicle_ids = list(filter(
            lambda x:
                self.waypoint.get_geohash(
                    self.vehicle_schedules[x][-1].route.goal_waypoint_id
                )[:TAXI_FLEET.DISPATCHABLE_GEOHASH_DIGIT] ==
                self.waypoint.get_geohash(
                    self.user_statuses[user_id].trip_schedules[0].route.start_waypoint_id
                )[:TAXI_FLEET.DISPATCHABLE_GEOHASH_DIGIT],
            self.vehicle_schedules.keys()
        ))
        # pp(dispatchable_vehicle_ids)
        return dispatchable_vehicle_ids

    def get_taxi_schedules(self, user_id, user_status):
        start_point = {
            "arrow_code": user_status.trip_schedules[0].route.arrow_codes[0],
            "waypoint_id": user_status.trip_schedules[0].route.start_waypoint_id,
        }
        vehicle_ids = self.get_dispatchable_vehicle_ids(user_id)
        if len(vehicle_ids) == 0:
            print("no dispatchable vehicles")
            return None, None

        goal_points = []
        for vehicle_id, goal_waypoint_id, goal_arrow_code in map(
                lambda x: (
                        x,
                        self.vehicle_schedules[x][-1].route.goal_waypoint_id,
                        self.vehicle_schedules[x][-1].route.arrow_codes[-1]),
                vehicle_ids):
            goal_points.append({
                "goal_id": vehicle_id,
                "arrow_code": goal_arrow_code,
                "waypoint_id": goal_waypoint_id,
            })
        routes = self.route.get_shortest_routes(start_point, goal_points, reverse=True)
        if len(routes) == 0:
            print("no pick_up_route")
            return None, None
        pick_up_route_reverse = \
            min(routes.items(), key=lambda x: x[1]["cost"] + self.vehicle_schedules[x[0]][-1].period.end)[1]

        vehicle_id = pick_up_route_reverse["goal_id"]

        start_point = {
            "arrow_code": user_status.trip_schedules[0].route.arrow_codes[0],
            "waypoint_id": user_status.trip_schedules[0].route.start_waypoint_id,
        }
        goal_points = [{
            "goal_id": user_id,
            "arrow_code": user_status.trip_schedules[0].route.arrow_codes[-1],
            "waypoint_id": user_status.trip_schedules[0].route.goal_waypoint_id,
        }]
        routes = self.route.get_shortest_routes(start_point, goal_points, reverse=False)
        if len(routes) == 0:
            print("cant carry_route")
            return None, None
        carry_route = min(routes.items(), key=lambda x: x[1]["cost"])[1]
        carry_route.pop("cost")
        carry_route.pop("goal_id")

        current_time = time()
        if self.vehicle_schedules[vehicle_id][-1].event == SimTaxi.CONST.STATE.STANDBY:
            current_time = self.vehicle_schedules[vehicle_id][-1].period.start
            # self.vehicle_schedules[vehicle_id].pop()
        pick_up_route = Route.new_route(
            pick_up_route_reverse.goal_waypoint_id, pick_up_route_reverse.start_waypoint_id,
            pick_up_route_reverse.arrow_codes)
        vehicle_schedule = Schedule.new_schedule(
            [
                Target.new_data(id=vehicle_id, group="SimTaxi"),
                Target.new_data(id=user_id, group="TaxiUser")
            ],
            Vehicle.CONST.ACTION.MOVE, current_time, current_time+1000, pick_up_route)
        vehicle_schedules = Schedule.get_merged_schedules(
            self.vehicle_schedules[vehicle_id], [vehicle_schedule])

        take_on_route = Route.new_point_route(pick_up_route.goal_waypoint_id, pick_up_route.arrow_codes[-1])
        vehicle_schedule = Schedule.new_schedule(
            [
                Target.new_data(id=vehicle_id, group="SimTaxi"),
                Target.new_data(id=user_id, group="TaxiUser")
            ],
            Vehicle.CONST.ACTION.STOP, current_time+1000, current_time+1010, take_on_route)
        vehicle_schedules = Schedule.get_merged_schedules(
            vehicle_schedules, [vehicle_schedule])

        vehicle_schedule = Schedule.new_schedule(
            [
                Target.new_data(id=vehicle_id, group="SimTaxi"),
                Target.new_data(id=user_id, group="TaxiUser")
            ],
            Vehicle.CONST.ACTION.MOVE, current_time+1010, current_time+2010, carry_route)
        vehicle_schedules = Schedule.get_merged_schedules(
            vehicle_schedules, [vehicle_schedule])

        discharge_route = Route.new_point_route(carry_route.goal_waypoint_id, carry_route.arrow_codes[-1])
        vehicle_schedule = Schedule.new_schedule(
            [
                Target.new_data(id=vehicle_id, group="SimTaxi"),
                Target.new_data(id=user_id, group="TaxiUser")
            ],
            Vehicle.CONST.ACTION.STOP, current_time+2010, current_time+2020, discharge_route)
        vehicle_schedules = Schedule.get_merged_schedules(
            vehicle_schedules, [vehicle_schedule])

        stand_by_route = Route.new_point_route(discharge_route.goal_waypoint_id, discharge_route.arrow_codes[-1])
        vehicle_schedule = Schedule.new_schedule(
            [
                Target.new_data(id=vehicle_id, group="SimTaxi"),
            ],
            SimTaxi.CONST.STATE.STANDBY, current_time+2020, current_time+86400, stand_by_route)
        vehicle_schedules = Schedule.get_merged_schedules(
            vehicle_schedules, [vehicle_schedule])

        return vehicle_id, vehicle_schedules

    def cleanup_status(self):
        user_ids = []
        for user_id, user_status in self.user_statuses.items():
            # print(time() - user_status.time, user_status.state)
            if TAXI_FLEET.TIMEOUT < time() - user_status.time:
                user_ids.append(user_id)
        for user_id in user_ids:
            if user_id in self.relations:
                for vehicle_id in self.relations[user_id]:
                    self.relations[vehicle_id].remove(user_id)
                    if len(self.relations[vehicle_id]) == 0:
                        self.relations.pop(vehicle_id)
                self.relations.pop(user_id)
            self.user_statuses.pop(user_id)
            self.user_schedules.pop(user_id)

    def update_status(self):
        self.cleanup_status()

        for user_id, user_status in self.user_statuses.items():
            if user_status.state == User.CONST.STATE.LOG_IN:
                pass
            elif user_status.state == TaxiUser.CONST.STATE.CALLING:
                if user_id not in self.relations:
                    vehicle_id, vehicle_schedules = self.get_taxi_schedules(user_id, user_status)
                    if vehicle_id is not None:
                        self.vehicle_schedules[vehicle_id] = vehicle_schedules
                        payload = self.topicVehicleSchedules.serialize(self.vehicle_schedules[vehicle_id])
                        self.publish(self.topicVehicleSchedules.root + "/" + vehicle_id + "/schedules", payload)

                        vehicle_ids = self.relations.get(user_id, [])
                        if vehicle_id not in vehicle_ids:
                            vehicle_ids.append(vehicle_id)
                        self.relations[user_id] = vehicle_ids

                        user_ids = self.relations.get(vehicle_id, [])
                        if user_id not in user_ids:
                            user_ids.append(user_id)
                        self.relations[vehicle_id] = user_ids

                if user_id in self.relations:
                    for vehicle_id in self.relations[user_id]:
                        if self.vehicle_statuses[vehicle_id].state == SimTaxi.CONST.STATE.MOVE_TO_USER:
                            self.user_schedules[user_id][0].event = TaxiUser.CONST.ACTION.WAIT
                            self.publish(
                                self.topicUserSubscribe.root + "/" + user_id + "/schedules",
                                self.topicUserSubscribe.serialize(self.user_schedules[user_id]))

            elif user_status.state == TaxiUser.CONST.STATE.WAITING:
                for vehicle_id in self.relations[user_id]:
                    if self.vehicle_statuses[vehicle_id].state == SimTaxi.CONST.STATE.STOP_FOR_PICKING_UP:
                        if user_id in map(lambda x: x.id, self.vehicle_schedules[vehicle_id][0].targets):
                            self.user_schedules[user_id][0].event = TaxiUser.CONST.ACTION.GET_ON
                            self.publish(
                                self.topicUserSubscribe.root+"/"+user_id+"/schedules",
                                self.topicUserSubscribe.serialize(self.user_schedules[user_id]))

            elif user_status.state == TaxiUser.CONST.STATE.GETTING_ON:
                pass

            elif user_status.state == TaxiUser.CONST.STATE.GOT_ON:
                for vehicle_id in self.relations[user_id]:
                    if user_id in map(lambda x: x.id, self.vehicle_schedules[vehicle_id][0].targets):
                        self.vehicle_schedules[vehicle_id][0].event = Vehicle.CONST.ACTION.MOVE
                        payload = self.topicVehicleSchedules.serialize(self.vehicle_schedules[vehicle_id])
                        self.publish(self.topicVehicleSchedules.root + "/" + vehicle_id + "/schedules", payload)

                        if self.vehicle_statuses[vehicle_id].state == SimTaxi.CONST.STATE.MOVE_TO_USER_DESTINATION:
                            self.user_schedules[user_id][0].event = TaxiUser.CONST.EVENT.MOVE_VEHICLE
                            self.publish(
                                self.topicUserSubscribe.root+"/"+user_id+"/schedules",
                                self.topicUserSubscribe.serialize(self.user_schedules[user_id]))

                        if self.vehicle_statuses[vehicle_id].state == SimTaxi.CONST.STATE.STOP_FOR_DISCHARGING:
                            self.user_schedules[user_id][0].event = TaxiUser.CONST.ACTION.GET_OUT
                            self.publish(
                                self.topicUserSubscribe.root+"/"+user_id+"/schedules",
                                self.topicUserSubscribe.serialize(self.user_schedules[user_id]))

            elif user_status.state == TaxiUser.CONST.STATE.MOVING:
                for vehicle_id in self.relations[user_id]:
                    if self.vehicle_statuses[vehicle_id].state == SimTaxi.CONST.STATE.STOP_FOR_DISCHARGING:
                        if user_id in map(lambda x: x.id, self.vehicle_schedules[vehicle_id][0].targets):
                            self.user_schedules[user_id][0].event = TaxiUser.CONST.ACTION.GET_OUT
                            self.publish(
                                self.topicUserSubscribe.root+"/"+user_id+"/schedules",
                                self.topicUserSubscribe.serialize(self.user_schedules[user_id]))

            elif user_status.state == TaxiUser.CONST.STATE.GETTING_OUT:
                pass

            elif user_status.state == TaxiUser.CONST.STATE.GOT_OUT:
                if user_id in self.relations:
                    for vehicle_id in self.relations[user_id]:
                        self.relations[vehicle_id].remove(user_id)
                        if len(self.relations[vehicle_id]) == 0:
                            self.relations.pop(vehicle_id)
                    self.relations.pop(user_id)

            elif user_status.state == User.CONST.STATE.LOG_OUT:
                if user_id in self.relations:
                    for vehicle_id in self.relations[user_id]:
                        self.relations[vehicle_id].remove(user_id)
                        if len(self.relations[vehicle_id]) == 0:
                            self.relations.pop(vehicle_id)
                    self.relations.pop(user_id)

            else:
                print("unknown user state", user_status.state)

        return
