import threading
import unittest
from valheim_codex.motion import MotionHeartbeat


class MotionTests(unittest.TestCase):
    def test_heartbeat_never_invents_a_movement_action(self):
        calls=[];called=threading.Event()
        class Client:
            def request(self,path,data,timeout):
                calls.append((path,data));called.set();return {"ok":True}
        motion=MotionHeartbeat(Client(),"epoch")
        self.assertTrue(called.wait(1))
        motion.close()
        self.assertTrue(all(x==('/control/travel-heartbeat',{'epoch':'epoch'}) for x in calls))
        self.assertFalse(motion.thread.is_alive())

    def test_disconnect_does_not_retry_or_resume(self):
        calls=[]
        class Client:
            def request(self,*args,**kwargs):
                calls.append(1);raise RuntimeError('disconnected')
        motion=MotionHeartbeat(Client(),"epoch")
        motion.thread.join(1)
        self.assertEqual(calls,[1])
        self.assertEqual(motion.failure,'RuntimeError')
        motion.close()

    def test_temporary_menu_rejection_does_not_disable_future_renewals(self):
        calls=[];renewed=threading.Event()
        class Client:
            def request(self,*args,**kwargs):
                calls.append(1)
                if len(calls)==1:return {'ok':False}
                renewed.set();return {'ok':True}
        motion=MotionHeartbeat(Client(),'same-epoch')
        self.assertTrue(renewed.wait(1))
        motion.close()
        self.assertGreaterEqual(len(calls),2)
