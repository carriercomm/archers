import logging
from Box2D import *
from archers.world import WorldObject, ReactorMixin, SelfDestructable, NetworkMixin, ProcessableMixin, directions
from archers.utils import vec2rad, rad2vec, getSpeedFromVec
from archers.items import items, get_slot_for
from collisions import CLCAT_CREATURE, CLCAT_BULLET, CLCAT_EVERYTHING, CLCAT_AIRBORNE_OBSTACLE, CLCAT_TERRESTRIAL_OBSTACLE, CLCAT_NOTHING
import settings


class Archer(WorldObject, ReactorMixin, NetworkMixin, ProcessableMixin):
	default_type = 'archer'
	collision_category = CLCAT_CREATURE
	collision_mask = CLCAT_NOTHING

	def __str__(self):
		if(self.player):
			return "{}[A]".format(self.player)

		return "__No_Player__[A]"
	

	def __init__(self, world, player=None, *args, **kwargs):
		self.speed = 1.0
		self.attack_speed = 1.0
		self.arrows_speed = 1.0
		self.player = player
		self.width = 1.0
		self.height = 1.5
		self.group_index = world.get_free_group_index()
		self.state = 'unknown'
		
		super(Archer, self).__init__(world, type="archer", *args, **kwargs)

	def spawn(self, spawn_point):
		self.state = 'standing'
		self.create_dynamic_box_body(
			spawn_point.x,
			spawn_point.y,
			self.width,
			self.height,
			density = 1
		)
		self.physics.fixedRotation = True
		self.physics.linearDamping = 25
		self.direction = directions['east']
		self.collision_mask = CLCAT_EVERYTHING ^ CLCAT_AIRBORNE_OBSTACLE
		self.update_collision_definition()
		self.interface.trigger('spawn')


	def attach_collision_data(self, fixture):
		super(Archer, self).attach_collision_data(fixture)
		fixture.filterData.groupIndex = self.group_index * -1

	def kill(self, pernament=False):
		if(not self.can_take_action()):
			return
		self.cancel_pending()
		self.want_stop()
		self.state = 'dying'
		self.collision_mask = CLCAT_NOTHING
		self.update_collision_definition()
		if(not hasattr(self, 'delayed_dying') or not self.delayed_dying.active()):
			self.delayed_dying = self.reactor.callLater(
				0.9,
				self.commit_kill
			)
		# self.world.physics.DestroyBody(self.physics)
		# self.physics = None

	def is_alive(self):
		return self.can_take_action()

	def can_take_action(self):
		if(self.state == 'walking' or self.state == 'standing' or self.state == 'shooting'):
			return True
		return False

	def destroy(self):
		self.cancel_pending()
		if(hasattr(self, 'player')):
			self.player = None
		if(hasattr(self, 'physics')):
			self.world.physics.DestroyBody(self.physics)
		if(hasattr(self, 'group_index')):
			self.world.release_group_index(self.group_index)
		super(Archer, self).destroy()

	def want_move(self, direction):
		if(not self.can_take_action()):
			return
		# import ipdb; ipdb.set_trace()
		if(not hasattr(direction, 'x')):
			direction = rad2vec(direction)
		self.cancel_pending()
		self.physics.linearVelocity = (0, 0)
		self.direction = direction
		self.state = "walking"

	def want_stop(self):
		if(not self.can_take_action()):
			return
		self.cancel_pending()
		self.physics.linearVelocity = (0, 0)
		self.state = "standing"

	def want_attack(self, direction):
		if(not self.can_take_action()):
			return
		if(not hasattr(direction, 'x')):
			direction = rad2vec(direction)

		self.want_stop()
		self.direction = direction
		if(not hasattr(self, 'delayed_attack') or not self.delayed_attack.active()):
			self.delayed_attack = self.reactor.callLater(
				0.75*self.get_attack_speed(),
				self.commit_attack,
				direction
			)
			self.state = "shooting"

	def commit_attack(self, direction):
		Arrow(direction, self.arrows_speed, self, reactor=self.reactor,
			lifetime=self.get_arrow_lifetime())

		self.want_stop()
		# self.arrows_shot.append(arrow)

	def commit_kill(self):
		self.state = "dead"
		logging.debug("Archer {} has died".format(self))
		if(not hasattr(self, 'delayed_cleanup') or not self.delayed_cleanup.active()):
			self.delayed_cleanup = self.reactor.callLater(
				1.0,
				self.commit_cleanup
			)

	def bump_into(self, other):
		diff_vector = other.physics.position - self.physics.position
		flat_vector = b2Vec2(round(diff_vector[0]), round(diff_vector[1]))
		self.want_stop()
		self.physics.ApplyForce(
			force = -10*flat_vector,
			point = self.physics.position,
			wake = True
		)


	def commit_cleanup(self):
		self.state = 'unknown'

	def cancel_pending(self):
		if(hasattr(self, 'delayed_attack') and self.delayed_attack.active()):
			self.delayed_attack.cancel()
		if(hasattr(self, 'delayed_dying') and self.delayed_dying.active()):
			self.delayed_dying.cancel()
		if(hasattr(self, 'delayed_cleanup') and self.delayed_cleanup.active()):
			self.delayed_cleanup.cancel()

	def get_arrow_lifetime(self):
		weapon_slot = get_slot_for('Weapon')
		if(weapon_slot):
			bow_id = self.interface.meta['slots'][weapon_slot]
			bow = items[bow_id]
			if "distance" in bow['properties']:
				return bow['properties']['distance']
		logging.warning("got invalid weapon_slot (%s) or bow definition (%s)."
			% (weapon_slot, bow))
		return 1.0

	def get_attack_speed(self):
		weapon_slot = get_slot_for('Weapon')
		if(weapon_slot):
			bow_id = self.interface.meta['slots'][weapon_slot]
			bow = items[bow_id]
			if "speed" in bow['properties']:
				return bow['properties']['speed']
		logging.warning("got invalid weapon_slot (%s) or bow definition (%s)."
			% (weapon_slot, bow))
		return 1.0

	def process(self):
		if(hasattr(self, 'direction') 
			and self.state == 'walking' 
			and self.direction
			and hasattr(self, 'physics')
			):
			speed_vector = self.direction*self.speed*settings.base_movement_speed
			self.physics.linearVelocity = speed_vector
			# max_speed_vector = self.direction*self.speed*settings.max_movement_speed
			# if(getSpeedFromVec(self.physics.linearVelocity) <= getSpeedFromVec(max_speed_vector)):
			# 	self.physics.ApplyForce(
			# 		force = speed_vector,
			# 		point = self.physics.position,
			# 		wake = True
			# 	)

class Arrow(SelfDestructable, NetworkMixin):
	collision_category = CLCAT_BULLET
	# collision_mask = CLCAT_OBSTACLE | CLCAT_AIRBORNE_OBSTACLE | CLCAT_CREATURE 
	# collision_mask = CLCAT_OBSTACLE | CLCAT_AIRBORNE_OBSTACLE | CLCAT_CREATURE
	# collision_mask = CLCAT_EVERYTHING ^ CLCAT_TERRESTRIAL_OBSTACLE
	collision_mask = CLCAT_EVERYTHING ^ CLCAT_TERRESTRIAL_OBSTACLE

	def __init__(self, direction, speed, owner, **kwargs):
		self.owner = owner
		self.speed = 1.0          
		self.width = 0.5 
		self.height = 0.15
		self.state = 'shooting'
		super(Arrow, self).__init__(
			owner.world,
			type="arrow",
			lifetime=kwargs.pop('lifetime', 1.0),
			**kwargs)

		target_position = b2Vec2(
			direction.x*(owner.width-self.width),
			direction.y*(owner.height-self.height)
		)
		target_position = owner.physics.position + target_position

		self.create_dynamic_box_body(
			target_position.x,
			target_position.y,
			self.width, self.height
		)

		self.physics.fixedRotation = True
		self.physics.linearDamping = 0.2
		self.direction = direction
		self.physics.angle = vec2rad(direction)

		speed_vector = b2Vec2(1,0)*self.speed*1.5
		self.physics.ApplyLinearImpulse(
			impulse=self.physics.GetWorldVector(speed_vector),
			point=self.physics.position,
			wake=True
		)
		self.physics.bullet = True
		# import ipdb; ipdb.set_trace()

	def attach_collision_data(self, fixture):
		super(Arrow, self).attach_collision_data(fixture)
		fixture.filterData.groupIndex = self.owner.group_index*-1

	def destroy(self):
		# self.owner.arrows_shot.remove(self)
		self.world.physics.DestroyBody(self.physics)
		super(Arrow, self).destroy()


class Skeleton(Archer):
	default_type = 'archer'
