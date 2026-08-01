// Generated from packages/contracts/schema. Do not edit manually.
import Ajv2020 from 'ajv/dist/2020.js'

import type { RetrievalResponse, SearchPayload, ChatPayload, ChatRequest, ChatResponse, InternalIdentity, InternalIdentityEnvelope, PilotRetrievalScopeArtifact } from './contracts'
import RetrievalResponseSchema from './schema/retrieval-response.json'
import SearchPayloadSchema from './schema/search-payload.json'
import ChatPayloadSchema from './schema/chat-payload.json'
import ChatRequestSchema from './schema/chat-request.json'
import ChatResponseSchema from './schema/chat-response.json'
import InternalIdentitySchema from './schema/internal-identity.json'
import InternalIdentityEnvelopeSchema from './schema/internal-identity-envelope.json'
import PilotRetrievalScopeArtifactSchema from './schema/pilot-retrieval-scope-artifact.json'

const ajv = new Ajv2020({ allErrors: true, strict: false })
const retrievalResponseValidator = ajv.compile<RetrievalResponse>(RetrievalResponseSchema)
const searchPayloadValidator = ajv.compile<SearchPayload>(SearchPayloadSchema)
const chatPayloadValidator = ajv.compile<ChatPayload>(ChatPayloadSchema)
const chatRequestValidator = ajv.compile<ChatRequest>(ChatRequestSchema)
const chatResponseValidator = ajv.compile<ChatResponse>(ChatResponseSchema)
const internalIdentityValidator = ajv.compile<InternalIdentity>(InternalIdentitySchema)
const internalIdentityEnvelopeValidator = ajv.compile<InternalIdentityEnvelope>(InternalIdentityEnvelopeSchema)
const pilotRetrievalScopeArtifactValidator = ajv.compile<PilotRetrievalScopeArtifact>(PilotRetrievalScopeArtifactSchema)

export const validateRetrievalResponse = (payload: unknown): payload is RetrievalResponse => retrievalResponseValidator(payload) === true

export const validateSearchPayload = (payload: unknown): payload is SearchPayload => searchPayloadValidator(payload) === true

export const validateChatPayload = (payload: unknown): payload is ChatPayload => chatPayloadValidator(payload) === true

export const validateChatRequest = (payload: unknown): payload is ChatRequest => chatRequestValidator(payload) === true

export const validateChatResponse = (payload: unknown): payload is ChatResponse => chatResponseValidator(payload) === true

export const validateInternalIdentity = (payload: unknown): payload is InternalIdentity => internalIdentityValidator(payload) === true

export const validateInternalIdentityEnvelope = (payload: unknown): payload is InternalIdentityEnvelope => internalIdentityEnvelopeValidator(payload) === true

export const validatePilotRetrievalScopeArtifact = (payload: unknown): payload is PilotRetrievalScopeArtifact => pilotRetrievalScopeArtifactValidator(payload) === true
