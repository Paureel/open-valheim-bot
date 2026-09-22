import unittest
import threading
import time
from types import SimpleNamespace
from valheim_codex.intents import Intent, validate_plan
from valheim_codex.motor import Motor
from valheim_codex.skills import InventorySkill
from valheim_codex.planner import Planner


def data(mode="travel"):
    return {"mode":mode,"objective":"reach visible clearing","target":"","heading":15,"distance":15,
            "seconds":30,"recipe_id":"","inventory_action":None}


def intent(mode="travel"):
    return Intent(1,"epoch","world-session",10,40,0,0,data(mode))


def evidence(frame=1, scores=None):
    return {"frame_id":frame,"captured_at":10.1,"revision":1,"epoch":"epoch",
            "support":scores or [.9,.5,.5,.1,.1,.1]}


class IntentTests(unittest.TestCase):
    def test_obsolete_plan_cancels_and_next_plan_uses_fresh_thread(self):
        started=threading.Event()
        class App:
            def __init__(self,config):self.last_usage={};self.threads=0
            def start_thread(self):self.threads+=1
            def plan(self,context,image,should_stop):
                if context['slow']:
                    started.set()
                    deadline=time.monotonic()+2
                    while not should_stop() and time.monotonic()<deadline:time.sleep(.01)
                    if should_stop():raise InterruptedError('obsolete')
                return {'done':True}
            def close(self):pass
        p=Planner(None,threading.Event(),factory=App)
        def response():
            deadline=time.monotonic()+1
            while time.monotonic()<deadline:
                value=p.poll()
                if value:return value
                time.sleep(.01)
            self.fail('planner did not respond')
        try:
            p.submit({'context':{'slow':True},'image':{}})
            self.assertTrue(started.wait(1));p.cancel()
            self.assertTrue(response()['cancelled'])
            p.submit({'context':{'slow':False},'image':{}})
            self.assertEqual(response()['plan'],{'done':True})
            self.assertEqual(p.app.threads,2)
        finally:p.close()

    def test_old_epoch_revision_frame_time_and_world_cannot_restart(self):
        i = intent(); e = evidence()
        self.assertTrue(i.accepts(e,10.5,"epoch","world-session"))
        for patch in ({"epoch":"old"},{"revision":0},{"captured_at":9.9},{"captured_at":10.6},{"captured_at":9}):
            self.assertFalse(i.accepts(dict(e,**patch),10.5,"epoch","world-session"))
        self.assertFalse(i.accepts(e,11.1,"epoch","world-session"))
        self.assertFalse(i.accepts(e,10.5,"epoch","different"))
        self.assertFalse(i.accepts(e,40,"epoch","world-session"))

    def test_source_image_heading_survives_cloud_latency(self):
        c={"epoch":"epoch","session_id":"s","view":{"camera_yaw":170},"status":{"locomotion":{"distance_m":9}}}
        i=Intent.create({"intent":data()},4,c,10)
        self.assertEqual(i.heading,-175)
        self.assertEqual(i.start_distance,9)
        self.assertIsNone(i.complete({"locomotion":{"distance_m":22}},11))
        self.assertIn("budget",i.complete({"locomotion":{"distance_m":24}},11))

    def test_untrusted_request_cannot_become_a_plan(self):
        cfg=SimpleNamespace(settings={"trusted_players_only_for_gameplay_requests":True,"combat_enabled":False},is_trusted=lambda e:False)
        p={"intent":data(),"note":"x","source_event_id":2,"speech":None,"memories":[]}
        c={"session_id":"s","conversation":[{"event_id":2,"session_id":"s"}]}
        with self.assertRaises(ValueError):validate_plan(p,cfg,c)
        p["source_event_id"]=None
        validate_plan(p,cfg,c)
        p["intent"]["mode"]="combat"
        with self.assertRaises(ValueError):validate_plan(p,cfg,c)

    def test_rest_never_moves_and_new_intent_requires_new_agreement(self):
        m=Motor();i=intent();s={"stamina":50}
        self.assertEqual(m.choose(i,evidence(),s,10.1)[0]["forward"],0)
        self.assertEqual(m.choose(i,evidence(2),s,10.6)[0]["forward"],1)
        self.assertIsNone(m.choose(i,evidence(2),s,10.7)[0])
        i=intent("rest");i.revision=2
        out,_=m.choose(i,evidence(3),s,11)
        self.assertEqual((out["forward"],out["yaw_rate"],out["button"]),(0,0,"none"))

    def test_untrusted_chat_can_reply_without_changing_intention(self):
        cfg=SimpleNamespace(settings={"trusted_players_only_for_gameplay_requests":True},is_trusted=lambda e:False)
        p={"intent":None,"note":"greeting","source_event_id":2,"speech":{"text":"Hey, how's the trail?","type":"normal","voluntary":False},"memories":[]}
        validate_plan(p,cfg,{"session_id":"s","conversation":[{"event_id":2,"session_id":"s"}]})

    def test_action_requires_target_name_on_caption_first_line(self):
        i=intent("gather");i.data["target"]="wood"
        scores=[.9,.5,.5,.1,.1,.1,.1,.95,.1]
        m=Motor()
        for f,caption in enumerate(("Beech\nUse wood to build", "Wooden chest\n[Use]"),1):
            out,_=m.choose(i,evidence(f,scores),{"hover_text":caption,"stamina":50},10+f)
            self.assertEqual(out["button"],"none")
        out,_=m.choose(i,evidence(3,scores),{"hover_text":"Wood\n[Use] Pick up","stamina":50},14)
        self.assertEqual(out["button"],"interact")

    def test_existing_destination_stack_does_not_prove_item_moved(self):
        i=intent("organize")
        i.data["inventory_action"]={"tool":"inventory_move","arguments":{"item_id":"a","to_x":1,"to_y":0,"amount":2}}
        skill=InventorySkill(i)
        status={"inventory":{"open":True,"items":[
            {"item_id":"a","name":"Wood","stack":5,"x":0,"y":0},
            {"item_id":"b","name":"Wood","stack":3,"x":1,"y":0}]}}
        self.assertEqual(skill.step(status)[0]["tool"],"inventory_move")
        self.assertIn("no verified change",skill.step(status)[1])
        status["inventory"]["items"][0]["stack"]=3
        status["inventory"]["items"][1]["stack"]=5
        self.assertEqual(skill.step(status)[0]["tool"],"close_inventory")

    def test_ambiguous_or_dangerous_image_stops_even_after_clear_motion(self):
        m=Motor();i=intent();s={"stamina":50}
        m.choose(i,evidence(),s,10.1);m.choose(i,evidence(2),s,10.5)
        for f,scores in enumerate(([.6,.6,.6,.4,.1,.4],[.99,.1,.1,.1,.7,.1]),3):
            out,_=m.choose(i,evidence(f,scores),s,11)
            self.assertEqual(out["forward"],0)
            self.assertEqual(out["button"],"none")

    def test_same_corridor_plan_extension_does_not_force_a_stop(self):
        m=Motor();i=intent();s={"stamina":50}
        m.choose(i,evidence(),s,10.1);m.choose(i,evidence(2),s,10.5)
        extension=intent();extension.revision=2
        out,_=m.choose(extension,evidence(3),s,11)
        self.assertEqual(out["forward"],1)
        changed=intent();changed.revision=3;changed.heading=30
        out,_=m.choose(changed,evidence(4),s,11.5)
        self.assertEqual(out["forward"],0)

    def test_turns_to_selected_corridor_before_rejecting_current_view(self):
        i=intent();i.heading=25
        out,reason=Motor().choose(i,evidence(scores=[.3,.8,.2,.8,.1,.8]),
            {"locomotion":{"camera_yaw":0},"stamina":50},10.5)
        self.assertEqual(reason,"turn toward intention")
        self.assertEqual(out["forward"],0)
        self.assertGreater(out["yaw_rate"],0)

    def test_clear_corridor_can_outscore_a_peripheral_stone(self):
        m=Motor();i=intent();s={"stamina":50}
        scores=[.87,.4,.4,.51,.01,.42]
        m.choose(i,evidence(1,scores),s,10.1)
        out,_=m.choose(i,evidence(2,scores),s,10.6)
        self.assertEqual(out['forward'],1)
        out,_=m.choose(i,evidence(3,[.87,.4,.4,.51,.01,.7]),s,11)
        self.assertEqual(out['forward'],0)

    def test_local_detour_turns_without_blind_movement_then_needs_clear_images(self):
        m=Motor();i=intent();s={'stamina':50,'locomotion':{'camera_yaw':0,'distance_m':0}}
        out,reason=m.choose(i,evidence(1,[.3,.7,.2,.6,.01,.5]),s,10.1)
        self.assertEqual(reason,'inspect local detour');self.assertEqual(out['forward'],0)
        self.assertLess(out['yaw_rate'],0)
        s['locomotion']['camera_yaw']=-30
        self.assertEqual(m.choose(i,evidence(2),s,10.6)[0]['forward'],0)
        self.assertEqual(m.choose(i,evidence(3),s,11.1)[0]['forward'],1)

    def test_collision_alone_cannot_jump_and_log_jump_has_cooldown(self):
        m=Motor();i=intent();s={"stamina":50,"locomotion":{"speed_mps":0}}
        out,_=m.choose(i,evidence(1,[.2,.1,.1,.2,.1,.9]),s,10.2)
        self.assertEqual(out["button"],"none")
        s["locomotion"]["camera_yaw"]=m.detour_heading
        out,_=m.choose(i,evidence(2,[.2,.1,.1,.9,.1,.9]),s,10.5)
        self.assertEqual(out["button"],"jump")
        out,_=m.choose(i,evidence(3,[.2,.1,.1,.9,.1,.9]),s,11)
        self.assertEqual(out["button"],"none")

    def test_craft_requires_actual_output_not_old_success_or_ack(self):
        i=intent("craft");i.data["recipe_id"]="axe"
        skill=InventorySkill(i)
        self.assertEqual(skill.step({})[0]["tool"],"open_inventory")
        inv={"open":True,"recipes":[{"recipe_id":"axe","name":"Stone axe","requirements_met":True}],
             "selected_recipe_id":"axe","can_craft":True,"last_craft":{"recipe_id":"axe","state":"completed"}}
        status={"inventory":inv,"supplies":[{"name":"Stone axe","count":1}]}
        self.assertEqual(skill.step(status)[0]["tool"],"select_recipe")
        self.assertEqual(skill.step(status)[0]["tool"],"craft_selected")
        self.assertIn("no verified output",skill.step(status)[1])
        status["supplies"][0]["count"]=2
        self.assertEqual(skill.step(status)[0]["tool"],"close_inventory")
        self.assertIn("verified",skill.step({"inventory":{"open":False}})[1])

    def test_explicit_close_inventory_does_not_reopen_or_inspect(self):
        i=intent("organize");i.data["inventory_action"]={"tool":"close_inventory","arguments":{}}
        skill=InventorySkill(i)
        self.assertEqual(skill.step({"inventory":{"open":True}})[0]["tool"],"close_inventory")
        self.assertEqual(skill.step({"inventory":{"open":False}}),(None,"inventory closed"))
        self.assertEqual(InventorySkill(i).step({"inventory":{"open":False}}),(None,"inventory closed"))


if __name__ == "__main__":
    unittest.main()
