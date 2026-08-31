// Generated from packages/contracts/schema. Do not edit manually.
import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'

import type { RetrievalRequest, RetrievalResponse, SearchPayload, ChatPayload, ChatRequest, ChatResponse, InternalIdentity, InternalIdentityEnvelope, PilotRetrievalScopeArtifact, RetrievalScopeArtifactV2, RetrievalScopeArtifactV3, ReviewQueuePayload, ReviewDecisionPayload, ReviewDecisionRequest, ReviewQueueResponse, ReviewDecisionResponse } from './contracts'
import RetrievalRequestSchema from './schema/retrieval-request.json'
import RetrievalResponseSchema from './schema/retrieval-response.json'
import SearchPayloadSchema from './schema/search-payload.json'
import ChatPayloadSchema from './schema/chat-payload.json'
import ChatRequestSchema from './schema/chat-request.json'
import ChatResponseSchema from './schema/chat-response.json'
import InternalIdentitySchema from './schema/internal-identity.json'
import InternalIdentityEnvelopeSchema from './schema/internal-identity-envelope.json'
import PilotRetrievalScopeArtifactSchema from './schema/pilot-retrieval-scope-artifact.json'
import RetrievalScopeArtifactV2Schema from './schema/retrieval-scope-artifact-v2.json'
import RetrievalScopeArtifactV3Schema from './schema/retrieval-scope-artifact-v3.json'
import ReviewQueuePayloadSchema from './schema/review-queue-payload.json'
import ReviewDecisionPayloadSchema from './schema/review-decision-payload.json'
import ReviewDecisionRequestSchema from './schema/review-decision-request.json'
import ReviewQueueResponseSchema from './schema/review-queue-response.json'
import ReviewDecisionResponseSchema from './schema/review-decision-response.json'

const ajv = new Ajv2020({ allErrors: true, strict: false })
addFormats(ajv)
const retrievalRequestValidator = ajv.compile<RetrievalRequest>(RetrievalRequestSchema)
const retrievalResponseValidator = ajv.compile<RetrievalResponse>(RetrievalResponseSchema)
const searchPayloadValidator = ajv.compile<SearchPayload>(SearchPayloadSchema)
const chatPayloadValidator = ajv.compile<ChatPayload>(ChatPayloadSchema)
const chatRequestValidator = ajv.compile<ChatRequest>(ChatRequestSchema)
const chatResponseValidator = ajv.compile<ChatResponse>(ChatResponseSchema)
const internalIdentityValidator = ajv.compile<InternalIdentity>(InternalIdentitySchema)
const internalIdentityEnvelopeValidator = ajv.compile<InternalIdentityEnvelope>(InternalIdentityEnvelopeSchema)
const pilotRetrievalScopeArtifactValidator = ajv.compile<PilotRetrievalScopeArtifact>(PilotRetrievalScopeArtifactSchema)
const retrievalScopeArtifactV2Validator = ajv.compile<RetrievalScopeArtifactV2>(RetrievalScopeArtifactV2Schema)
const retrievalScopeArtifactV3Validator = ajv.compile<RetrievalScopeArtifactV3>(RetrievalScopeArtifactV3Schema)
const reviewQueuePayloadValidator = ajv.compile<ReviewQueuePayload>(ReviewQueuePayloadSchema)
const reviewDecisionPayloadValidator = ajv.compile<ReviewDecisionPayload>(ReviewDecisionPayloadSchema)
const reviewDecisionRequestValidator = ajv.compile<ReviewDecisionRequest>(ReviewDecisionRequestSchema)
const reviewQueueResponseValidator = ajv.compile<ReviewQueueResponse>(ReviewQueueResponseSchema)
const reviewDecisionResponseValidator = ajv.compile<ReviewDecisionResponse>(ReviewDecisionResponseSchema)

export const validateRetrievalRequest = (payload: unknown): payload is RetrievalRequest => retrievalRequestValidator(payload) === true

export const validateRetrievalResponse = (payload: unknown): payload is RetrievalResponse => retrievalResponseValidator(payload) === true

export const validateSearchPayload = (payload: unknown): payload is SearchPayload => searchPayloadValidator(payload) === true

export const validateChatPayload = (payload: unknown): payload is ChatPayload => chatPayloadValidator(payload) === true

export const validateChatRequest = (payload: unknown): payload is ChatRequest => chatRequestValidator(payload) === true

export const validateChatResponse = (payload: unknown): payload is ChatResponse => chatResponseValidator(payload) === true

export const validateInternalIdentity = (payload: unknown): payload is InternalIdentity => internalIdentityValidator(payload) === true

export const validateInternalIdentityEnvelope = (payload: unknown): payload is InternalIdentityEnvelope => internalIdentityEnvelopeValidator(payload) === true

export const validatePilotRetrievalScopeArtifact = (payload: unknown): payload is PilotRetrievalScopeArtifact => pilotRetrievalScopeArtifactValidator(payload) === true

export const validateRetrievalScopeArtifactV2 = (payload: unknown): payload is RetrievalScopeArtifactV2 => retrievalScopeArtifactV2Validator(payload) === true

export const validateRetrievalScopeArtifactV3 = (payload: unknown): payload is RetrievalScopeArtifactV3 => retrievalScopeArtifactV3Validator(payload) === true

export const validateReviewQueuePayload = (payload: unknown): payload is ReviewQueuePayload => reviewQueuePayloadValidator(payload) === true

export const validateReviewDecisionPayload = (payload: unknown): payload is ReviewDecisionPayload => reviewDecisionPayloadValidator(payload) === true

export const validateReviewDecisionRequest = (payload: unknown): payload is ReviewDecisionRequest => reviewDecisionRequestValidator(payload) === true

export const validateReviewQueueResponse = (payload: unknown): payload is ReviewQueueResponse => reviewQueueResponseValidator(payload) === true && payload.returned === payload.documents.length

export const validateReviewDecisionResponse = (payload: unknown): payload is ReviewDecisionResponse => reviewDecisionResponseValidator(payload) === true
